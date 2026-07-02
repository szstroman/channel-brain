"""
indexer.py  -  Fetch all videos from a YouTube channel and index into Pinecone.
"""

import os
import re
import json
import time
from pathlib import Path
from typing import Optional

# Load .env file if present (local dev). On Railway, env vars are set directly
# so python-dotenv finding nothing is harmless.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec


# ── Embedding model (loaded once, reused) ─────────────────────────────────────
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


# ── Pinecone client ────────────────────────────────────────────────────────────

def get_pinecone_index(index_name: str = "channel-brain-prod"):
    """Return a connected Pinecone index. Raises clearly if API key missing."""
    api_key = os.environ.get("PINECONE_API_KEY")
    if not api_key:
        raise ValueError(
            "PINECONE_API_KEY environment variable is not set. "
            "Add it to your .env file or Railway environment variables."
        )
    pc = Pinecone(api_key=api_key)

    # Create index if it doesn't exist yet
    existing = [i.name for i in pc.list_indexes()]
    if index_name not in existing:
        pc.create_index(
            name=index_name,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        # Wait for index to be ready
        time.sleep(5)

    return pc.Index(index_name)


# ── Helpers (unchanged from v1) ────────────────────────────────────────────────

def extract_channel_id(url: str, youtube) -> tuple[str, str]:
    """Return (channel_id, channel_name) from a URL like @handle or /channel/ID."""
    url = url.strip().rstrip("/")

    handle_match = re.search(r"@([\w.-]+)", url)
    if handle_match:
        handle = handle_match.group(1)
        resp = youtube.search().list(
            part="snippet", q=handle, type="channel", maxResults=1
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Could not find channel for handle @{handle}")
        channel_id = items[0]["snippet"]["channelId"]
        channel_name = items[0]["snippet"]["channelTitle"]
        return channel_id, channel_name

    channel_match = re.search(r"channel/(UC[\w-]+)", url)
    if channel_match:
        channel_id = channel_match.group(1)
        resp = youtube.channels().list(part="snippet", id=channel_id).execute()
        name = resp["items"][0]["snippet"]["title"]
        return channel_id, name

    raise ValueError("Could not parse channel URL. Use format: https://www.youtube.com/@channelname")


def get_uploads_playlist(channel_id: str, youtube) -> str:
    resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    return resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_uploads_playlist_and_count(channel_id: str, youtube) -> tuple[str, int]:
    """
    Fetch uploads playlist ID and total video count in a single API call.
    Returns (playlist_id, video_count).
    """
    try:
        resp = youtube.channels().list(
            part="contentDetails,statistics", id=channel_id
        ).execute()
        item = resp["items"][0]
        playlist_id = item["contentDetails"]["relatedPlaylists"]["uploads"]
        count = int(item["statistics"].get("videoCount", 0))
        return playlist_id, count if count > 0 else 5000
    except Exception:
        # Fallback: get playlist only, use safe large count
        playlist_id = get_uploads_playlist(channel_id, youtube)
        return playlist_id, 5000


def get_all_video_ids(playlist_id: str, youtube, max_videos: int) -> list[dict]:
    videos = []
    next_page = None
    while len(videos) < max_videos:
        resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=min(50, max_videos - len(videos)),
            pageToken=next_page,
        ).execute()
        for item in resp.get("items", []):
            snippet = item["snippet"]
            vid_id = snippet["resourceId"]["videoId"]
            title = snippet["title"]
            videos.append({"id": vid_id, "title": title})
        next_page = resp.get("nextPageToken")
        if not next_page:
            break
    return videos


def fetch_transcript(video_id: str, max_retries: int = 3) -> Optional[str]:
    """
    Fetch transcript text for a video with retry logic.
    Retries on transient errors (rate limiting, network) with exponential backoff.
    Returns None only if all retries exhausted or transcript genuinely unavailable.
    """
    cookies_path = Path("cookies.txt")

    def make_api():
        if cookies_path.exists():
            import http.cookiejar
            import requests
            jar = http.cookiejar.MozillaCookieJar()
            jar.load(str(cookies_path), ignore_discard=True, ignore_expires=True)
            session = requests.Session()
            session.cookies = jar
            return YouTubeTranscriptApi(http_client=session)
        return YouTubeTranscriptApi()

    last_error = None

    for attempt in range(max_retries):
        # Exponential backoff before retries: 0s, 5s, 15s
        if attempt > 0:
            wait = 5 * (3 ** (attempt - 1))  # 5s, 15s
            wait = min(wait, 60)
            time.sleep(wait)

        ytt = make_api()

        # Method 1: direct fetch
        try:
            result = ytt.fetch(video_id, languages=["en", "en-US", "en-GB"])
            return " ".join(
                chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                for chunk in result.to_raw_data()
            )
        except Exception as e:
            last_error = e

        # Method 2: list available transcripts
        try:
            transcript_list = ytt.list(video_id)
            for t in transcript_list:
                result = t.fetch()
                return " ".join(
                    chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                    for chunk in result.to_raw_data()
                )
        except Exception as e:
            last_error = e

        # If error indicates transcript genuinely doesn't exist, don't retry
        if last_error:
            err_str = str(last_error).lower()
            if "transcripts disabled" in err_str or "no transcripts" in err_str or "video unavailable" in err_str:
                return None

    return None


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


def namespace_from_name(channel_name: str) -> str:
    """Convert channel name to a safe Pinecone namespace slug."""
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", channel_name).lower()
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60]


# ── Main build function ────────────────────────────────────────────────────────

def build_index(channel_url: str, max_videos: int = 50,
                client_id: str = None,
                index_name: str = "channel-brain-prod",
                progress_callback=None) -> tuple[dict, dict]:
    """
    Fetches all videos, transcribes them, embeds chunks, and upserts to Pinecone.
    Returns (pinecone_config, stats_dict).
    """
    api_key = os.environ["YOUTUBE_API_KEY"]
    youtube = build("youtube", "v3", developerKey=api_key)

    # 1. Resolve channel
    if progress_callback:
        progress_callback.progress(0.05, text="Resolving channel...")
    channel_id, channel_name = extract_channel_id(channel_url, youtube)

    # Determine namespace
    namespace = client_id if client_id else namespace_from_name(channel_name)

    # 2. Get video list — fetch playlist ID and count in one API call
    playlist_id, total_videos = get_uploads_playlist_and_count(channel_id, youtube)

    if not max_videos:
        # Use real video count so we always index the full channel
        max_videos = total_videos
        if progress_callback:
            progress_callback.progress(0.1, text=f"Found {max_videos} videos on channel. Fetching list...")
    else:
        if progress_callback:
            progress_callback.progress(0.1, text=f"Found channel: {channel_name}. Getting video list...")

    videos = get_all_video_ids(playlist_id, youtube, max_videos)

    # 3. Connect to Pinecone
    if progress_callback:
        progress_callback.progress(0.12, text="Connecting to Pinecone...")
    pinecone_index = get_pinecone_index(index_name)
    model = get_model()

    # 4. Fetch transcripts + embed + upsert
    stats = {
        "channel_name": channel_name,
        "channel_id": channel_id,
        "namespace": namespace,
        "index_name": index_name,
        "videos_indexed": 0,
        "skipped": 0,
        "skipped_titles": [],
        "total_chunks": 0,
        "total_videos_on_channel": total_videos,
        "last_sync_date": time.strftime("%Y-%m-%d"),
        "videos": [],
    }

    for i, video in enumerate(videos):
        progress_pct = 0.15 + (0.80 * i / len(videos))
        if progress_callback:
            progress_callback.progress(
                progress_pct,
                text=f"({i+1}/{len(videos)}) {video['title'][:50]}..."
            )

        transcript = fetch_transcript(video["id"])
        if not transcript:
            stats["skipped"] += 1
            stats["skipped_titles"].append(video["title"])
            time.sleep(1.0)
            continue

        chunks = chunk_text(transcript)

        # Embed all chunks for this video
        embeddings = model.encode(chunks, show_progress_bar=False).tolist()

        # Build vectors for Pinecone upsert
        vectors = []
        for j, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vectors.append({
                "id": f"{video['id']}_{j}",
                "values": embedding,
                "metadata": {
                    "text": chunk,
                    "video_id": video["id"],
                    "title": video["title"],
                    "url": f"https://www.youtube.com/watch?v={video['id']}",
                    "chunk_index": j,
                }
            })

        # Upsert in batches of 100 (Pinecone recommended batch size)
        batch_size = 100
        for batch_start in range(0, len(vectors), batch_size):
            batch = vectors[batch_start:batch_start + batch_size]
            pinecone_index.upsert(vectors=batch, namespace=namespace)

        stats["videos_indexed"] += 1
        stats["total_chunks"] += len(chunks)
        stats["videos"].append({"id": video["id"], "title": video["title"]})

        time.sleep(0.8)

    # 5. Save stats to /data (Railway volume) or local indexes/
    pinecone_config = {
        "stats": stats,
        "pinecone_index": index_name,
        "namespace": namespace,
    }

    # Try Railway volume first, fall back to local
    save_dirs = ["/data", "indexes"]
    for save_dir in save_dirs:
        try:
            Path(save_dir).mkdir(exist_ok=True)
            stats_path = f"{save_dir}/{namespace}.json"
            with open(stats_path, "w") as f:
                json.dump(pinecone_config, f, indent=2)
            break
        except Exception:
            continue

    if progress_callback:
        progress_callback.progress(1.0, text="Done!")

    return pinecone_config, stats


# ── Load existing index metadata ───────────────────────────────────────────────

def load_index(json_path: str) -> tuple[object, dict]:
    """
    Load index metadata from JSON.
    Returns (pinecone_index_object, stats_dict).
    """
    with open(json_path) as f:
        data = json.load(f)

    stats = data["stats"]
    index_name = data.get("pinecone_index", "channel-brain-prod")
    namespace = data.get("namespace", stats.get("namespace", ""))

    # Validate Pinecone key exists before attempting connection
    if not os.environ.get("PINECONE_API_KEY"):
        raise ValueError(
            "PINECONE_API_KEY not set. Cannot load index."
        )

    pinecone_index = get_pinecone_index(index_name)

    # Verify namespace has vectors
    try:
        ns_stats = pinecone_index.describe_index_stats()
        namespaces = ns_stats.get("namespaces", {})
        if namespace not in namespaces:
            raise ValueError(
                f"Namespace '{namespace}' not found in Pinecone index '{index_name}'. "
                f"Run build_index() first."
            )
    except Exception as e:
        if "Namespace" in str(e):
            raise
        # Other errors (network etc) — proceed and let query fail gracefully
        pass

    # Return a wrapper dict that carries namespace info for queries
    index_wrapper = {
        "pinecone_index": pinecone_index,
        "namespace": namespace,
    }

    return index_wrapper, stats


# ── Delta sync ─────────────────────────────────────────────────────────────────

def delta_sync(client_id: str, channel_url: str,
               index_name: str = "channel-brain-prod",
               dry_run: bool = False,
               max_videos_to_check: int = 500) -> dict:
    """
    Check a client's YouTube channel for new videos and index only the new ones.
    Designed to be called by the weekly sync_runner.

    Args:
        client_id:              Client identifier — must match namespace and stats file name.
        channel_url:            Full YouTube channel URL (e.g., https://youtube.com/@handle).
        index_name:             Pinecone index name. Defaults to production index.
        dry_run:                If True, checks for new videos but does NOT index them.
                                Useful for testing sync_runner without touching Pinecone.
        max_videos_to_check:    How far back to check the channel's uploads playlist.
                                Default 500 covers ~10 years of typical creator uploads.

    Returns dict with:
        client_id:              Echoed back for logging.
        status:                 "ok" | "no_new_videos" | "no_existing_index" | "error"
        synced:                 Count of successfully indexed videos.
        skipped:                Count of videos that failed transcript fetch (rate limit / unavailable).
        new_video_titles:       List of titles that were successfully synced.
        skipped_video_ids:      IDs of videos that failed — useful for resync_skipped follow-up.
        message:                Human-readable summary.
        error:                  Only present if status == "error".
    """
    result = {
        "client_id": client_id,
        "status": "ok",
        "synced": 0,
        "skipped": 0,
        "new_video_titles": [],
        "skipped_video_ids": [],
        "message": "",
    }

    # Defensive input validation — even though sync_runner should pass sanitized
    # values from clients.json, we guard against direct calls with bad input.
    if not client_id or not isinstance(client_id, str):
        result["status"] = "error"
        result["error"] = "client_id must be a non-empty string"
        return result

    # Basic sanitization: alphanumeric, hyphens, underscores only
    # (matches the validation in clients_config.sanitize_client_id)
    import re as _re
    if not _re.match(r"^[a-z0-9_-]+$", client_id):
        result["status"] = "error"
        result["error"] = f"client_id contains invalid characters: '{client_id}'"
        return result

    if not channel_url or not isinstance(channel_url, str):
        result["status"] = "error"
        result["error"] = "channel_url must be a non-empty string"
        return result

    # Load existing stats — required to know what's already indexed
    stats_path = None
    for search_dir in ["/data", "indexes"]:
        candidate = f"{search_dir}/{client_id}.json"
        if Path(candidate).exists():
            stats_path = candidate
            break

    if not stats_path:
        result["status"] = "no_existing_index"
        result["message"] = f"No index file found for '{client_id}'. Run build_index first."
        return result

    try:
        with open(stats_path) as f:
            data = json.load(f)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Could not read stats file: {e}"
        return result

    stats = data.get("stats", {})
    indexed_ids = {v["id"] for v in stats.get("videos", []) if "id" in v}
    namespace = data.get("namespace", client_id)

    # Fetch current video list from YouTube
    try:
        api_key = os.environ["YOUTUBE_API_KEY"]
        youtube = build("youtube", "v3", developerKey=api_key)
        channel_id, _ = extract_channel_id(channel_url, youtube)
        playlist_id = get_uploads_playlist(channel_id, youtube)
        all_videos = get_all_video_ids(playlist_id, youtube, max_videos=max_videos_to_check)
    except KeyError:
        result["status"] = "error"
        result["error"] = "YOUTUBE_API_KEY not set in environment"
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"YouTube API error: {e}"
        return result

    # Determine which videos are new
    new_videos = [v for v in all_videos if v["id"] not in indexed_ids]

    if not new_videos:
        result["status"] = "no_new_videos"
        result["message"] = "No new videos found since last sync"
        return result

    # Dry-run stops here — report what WOULD sync without actually syncing
    if dry_run:
        result["message"] = f"[dry-run] Would sync {len(new_videos)} new videos"
        result["new_video_titles"] = [v.get("title", "(untitled)") for v in new_videos]
        return result

    # Real sync begins here — connect to Pinecone
    try:
        pinecone_index = get_pinecone_index(index_name)
        model = get_model()
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Could not connect to Pinecone or load embedding model: {e}"
        return result

    # Process each new video with per-video error handling and partial-progress save.
    # Uses R1-03's rate-limiting lessons: 3s delay, fetch_transcript has retries built in.
    for video in new_videos:
        video_id = video["id"]
        title = video.get("title", "(untitled)")

        try:
            transcript = fetch_transcript(video_id)
            if not transcript:
                # Skipped — either rate-limited or genuinely unavailable
                result["skipped"] += 1
                result["skipped_video_ids"].append(video_id)
                time.sleep(3.0)  # honor rate-limit backoff even on skip
                continue

            chunks = chunk_text(transcript)
            embeddings = model.encode(chunks, show_progress_bar=False).tolist()

            vectors = [{
                "id": f"{video_id}_{j}",
                "values": emb,
                "metadata": {
                    "text": chunk,
                    "video_id": video_id,
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "chunk_index": j,
                }
            } for j, (chunk, emb) in enumerate(zip(chunks, embeddings))]

            for batch_start in range(0, len(vectors), 100):
                batch = vectors[batch_start:batch_start + 100]
                pinecone_index.upsert(vectors=batch, namespace=namespace)

            # Update stats IN MEMORY, save to disk each video (partial-progress preservation)
            stats.setdefault("videos", []).append({"id": video_id, "title": title})
            stats["videos_indexed"] = stats.get("videos_indexed", 0) + 1
            stats["total_chunks"] = stats.get("total_chunks", 0) + len(chunks)
            data["stats"] = stats

            # Save after EVERY video — if we crash on video N, videos 1..N-1 stay saved
            try:
                with open(stats_path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as save_err:
                # Non-fatal — log but continue
                print(f"[delta_sync] warning: could not save stats after {video_id}: {save_err}")

            result["synced"] += 1
            result["new_video_titles"].append(title)

            time.sleep(3.0)  # R1-03 lesson: 3s delay is safe, 0.8s got us rate-limited

        except Exception as e:
            # One bad video doesn't kill the whole sync
            result["skipped"] += 1
            result["skipped_video_ids"].append(video_id)
            print(f"[delta_sync] error on {video_id}: {e}")
            time.sleep(3.0)
            continue

    # Final metadata update
    stats["last_sync_date"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    data["stats"] = stats
    try:
        with open(stats_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as save_err:
        print(f"[delta_sync] warning: could not save final stats: {save_err}")

    result["message"] = (
        f"Synced {result['synced']}/{len(new_videos)} new videos "
        f"({result['skipped']} skipped)"
    )
    return result
