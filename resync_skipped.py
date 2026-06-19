"""
resync_skipped.py

Re-attempts transcript fetching for videos that were skipped during the
initial build_index run. Only processes videos NOT already in the Pinecone
namespace, so it's safe to run multiple times.

Usage:
    1. Make sure VPN is on
    2. Edit the config block below to match your client
    3. Run: python resync_skipped.py

The script:
  - Reads the existing stats JSON from /data/ or indexes/
  - Fetches the full current YouTube video list
  - Identifies videos NOT yet in the Pinecone namespace
  - Re-fetches transcripts using the new retry logic (5s/15s/45s backoff)
  - Upserts new vectors to the SAME namespace
  - Updates the stats JSON when done
  - Uses 3-second delay between videos (vs 0.8s in build_index) to be polite
"""

import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
CHANNEL_URL = "https://www.youtube.com/@thekoerneroffice"
CLIENT_ID   = "koerner-office"
INDEX_NAME  = "channel-brain-prod"  # match what you used in build_index.py

# Delay between videos. Higher = slower but safer from rate limiting.
# Original build_index uses 0.8s. This is much more conservative.
DELAY_BETWEEN_VIDEOS = 3.0

# ── Validate keys ─────────────────────────────────────────────────────────────
if not os.environ.get("YOUTUBE_API_KEY"):
    print("❌ ERROR: YOUTUBE_API_KEY not set in .env")
    sys.exit(1)
if not os.environ.get("PINECONE_API_KEY"):
    print("❌ ERROR: PINECONE_API_KEY not set in .env")
    sys.exit(1)

from googleapiclient.discovery import build
from indexer import (
    extract_channel_id, get_uploads_playlist_and_count,
    get_all_video_ids, fetch_transcript, chunk_text,
    get_pinecone_index, get_model
)

# ── Locate existing stats JSON ────────────────────────────────────────────────
stats_path = None
for search_dir in ["/data", "indexes"]:
    candidate = Path(search_dir) / f"{CLIENT_ID}.json"
    if candidate.exists():
        stats_path = str(candidate)
        break

if not stats_path:
    print(f"❌ ERROR: No existing stats file found for {CLIENT_ID}")
    print(f"   Looked in: /data/{CLIENT_ID}.json and indexes/{CLIENT_ID}.json")
    print(f"   Run build_index.py first.")
    sys.exit(1)

print(f"Loading stats from: {stats_path}")
with open(stats_path) as f:
    data = json.load(f)

stats = data["stats"]
namespace = data.get("namespace", CLIENT_ID)
already_indexed_ids = {v["id"] for v in stats.get("videos", [])}

print(f"Channel  : {stats['channel_name']}")
print(f"Namespace: {namespace}")
print(f"Already indexed: {len(already_indexed_ids)} videos")

# ── Fetch full current video list from YouTube ────────────────────────────────
print(f"\nFetching current video list from YouTube...")
youtube = build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])
channel_id, _ = extract_channel_id(CHANNEL_URL, youtube)
playlist_id, total_videos = get_uploads_playlist_and_count(channel_id, youtube)
all_videos = get_all_video_ids(playlist_id, youtube, max_videos=total_videos)

# ── Identify what still needs indexing ────────────────────────────────────────
missing_videos = [v for v in all_videos if v["id"] not in already_indexed_ids]

print(f"Total on channel : {len(all_videos)}")
print(f"Already indexed  : {len(already_indexed_ids)}")
print(f"Need to retry    : {len(missing_videos)}")

if not missing_videos:
    print("\n✅ Nothing to do - all videos already indexed!")
    sys.exit(0)

print(f"\nDelay between videos: {DELAY_BETWEEN_VIDEOS}s")
print(f"Estimated time: {(len(missing_videos) * DELAY_BETWEEN_VIDEOS) / 60:.0f} min minimum")
print("-" * 60)

# ── Connect to Pinecone + load model ──────────────────────────────────────────
pinecone_index = get_pinecone_index(INDEX_NAME)
model = get_model()

# ── Re-attempt each missing video ─────────────────────────────────────────────
recovered = 0
still_failed = 0
still_failed_titles = []

for i, video in enumerate(missing_videos):
    title_short = video["title"][:55]
    print(f"\r[{i+1}/{len(missing_videos)}] {title_short}...", end="", flush=True)

    transcript = fetch_transcript(video["id"], max_retries=3)

    if not transcript:
        still_failed += 1
        still_failed_titles.append(video["title"])
        time.sleep(DELAY_BETWEEN_VIDEOS)
        continue

    chunks = chunk_text(transcript)
    embeddings = model.encode(chunks, show_progress_bar=False).tolist()

    vectors = [{
        "id": f"{video['id']}_{j}",
        "values": emb,
        "metadata": {
            "text": chunk,
            "video_id": video["id"],
            "title": video["title"],
            "url": f"https://www.youtube.com/watch?v={video['id']}",
            "chunk_index": j,
        }
    } for j, (chunk, emb) in enumerate(zip(chunks, embeddings))]

    # Upsert in batches of 100
    for batch_start in range(0, len(vectors), 100):
        batch = vectors[batch_start:batch_start + 100]
        pinecone_index.upsert(vectors=batch, namespace=namespace)

    # Track progress
    stats["videos"].append({"id": video["id"], "title": video["title"]})
    stats["videos_indexed"] = stats.get("videos_indexed", 0) + 1
    stats["total_chunks"] = stats.get("total_chunks", 0) + len(chunks)
    recovered += 1

    # Save stats after every successful video — if rate-limited we don't lose progress
    stats["last_sync_date"] = time.strftime("%Y-%m-%d")
    data["stats"] = stats
    with open(stats_path, "w") as f:
        json.dump(data, f, indent=2)

    time.sleep(DELAY_BETWEEN_VIDEOS)

# ── Final summary ─────────────────────────────────────────────────────────────
print(f"\n\n{'='*60}")
print(f"RESYNC COMPLETE")
print(f"{'='*60}")
print(f"Recovered           : {recovered}")
print(f"Still failed        : {still_failed}")
print(f"Total in namespace  : {stats['videos_indexed']} / {len(all_videos)} on channel")

if still_failed_titles:
    print(f"\nStill failed after retry:")
    for t in still_failed_titles[:20]:
        print(f"   - {t}")
    if len(still_failed_titles) > 20:
        print(f"   ... and {len(still_failed_titles)-20} more")
    print(f"\nIf this list is large, your IP may still be rate-limited.")
    print(f"Wait a few hours and run resync_skipped.py again - it will resume from where it left off.")
