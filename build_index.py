"""
build_index.py

Run this ONCE locally (with VPN on) to index a channel into Pinecone.
Use your DEV Pinecone account for testing, PROD for real clients.

Usage:
    python build_index.py

To index into dev account: set PINECONE_API_KEY to your dev key in .env
To index into prod account: set PINECONE_API_KEY to your prod key in .env
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

CHANNEL_URL      = "https://www.youtube.com/@thekoerneroffice"
CLIENT_ID        = "koerner-office"   # becomes the Pinecone namespace
MAX_VIDEOS       = 0                  # 0 = auto-detect from YouTube (indexes everything)
INDEX_NAME       = "channel-brain-prod"  # change to "channel-brain-dev" for testing

# ── Validate keys before starting ─────────────────────────────────────────────
YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
PINECONE_API_KEY  = os.environ.get("PINECONE_API_KEY")

missing = []
if not YOUTUBE_API_KEY:  missing.append("YOUTUBE_API_KEY")
if not PINECONE_API_KEY: missing.append("PINECONE_API_KEY")

if missing:
    print(f"❌ ERROR: Missing environment variables: {', '.join(missing)}")
    print("   Make sure your .env file contains these keys.")
    sys.exit(1)

# ── Run index build ────────────────────────────────────────────────────────────
from indexer import build_index

print(f"Starting index build")
print(f"  Channel  : {CHANNEL_URL}")
print(f"  Client ID: {CLIENT_ID}")
print(f"  Namespace: {CLIENT_ID}")
print(f"  Index    : {INDEX_NAME}")
print(f"  Max videos: {MAX_VIDEOS}")
print("-" * 50)

class SimpleProgress:
    def progress(self, pct, text=""):
        bar = "█" * int(pct * 30) + "░" * (30 - int(pct * 30))
        print(f"\r[{bar}] {int(pct*100)}% — {text[:60]}", end="", flush=True)

pinecone_config, stats = build_index(
    CHANNEL_URL,
    MAX_VIDEOS,
    client_id=CLIENT_ID,
    index_name=INDEX_NAME,
    progress_callback=SimpleProgress()
)

print(f"\n\n✅ Done!")
print(f"   Channel   : {stats['channel_name']}")
print(f"   Namespace : {stats['namespace']}")
print(f"   Videos    : {stats['videos_indexed']} indexed / {stats.get('total_videos_on_channel', 'unknown')} on channel")
print(f"   Chunks    : {stats['total_chunks']}")
print(f"   Skipped   : {stats['skipped']}")

if stats.get("skipped_titles"):
    print(f"\nSkipped (no transcript):")
    for t in stats["skipped_titles"]:
        print(f"   - {t}")

print(f"\nVectors are live in Pinecone namespace: '{stats['namespace']}'")
print(f"The demo app will load this automatically on next startup.")
