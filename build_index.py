"""
build_index.py

Run this ONCE locally before deploying to Streamlit Cloud.
It indexes The Koerner Office and saves the ChromaDB to disk.
You will then commit the indexes/ folder to GitHub.

Usage:
    python build_index.py
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

# ── Set your keys here for local runs only ────────────────────────────────────
# OR set them as environment variables before running:
#   set YOUTUBE_API_KEY=your_key   (Windows)
#   export YOUTUBE_API_KEY=your_key  (Mac)

YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

if not YOUTUBE_API_KEY or not ANTHROPIC_API_KEY:
    print("❌ ERROR: API keys not found. Make sure your .env file exists and contains:")
    print("   YOUTUBE_API_KEY=your_key")
    print("   ANTHROPIC_API_KEY=your_key")
    import sys; sys.exit(1)
CHANNEL_URL      = "https://www.youtube.com/@thekoerneroffice"
MAX_VIDEOS       = 100  # Start with 100; increase to 300+ once confirmed working

# ─────────────────────────────────────────────────────────────────────────────

os.environ["YOUTUBE_API_KEY"]   = YOUTUBE_API_KEY
os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

from indexer import build_index

print(f"Starting index build for: {CHANNEL_URL}")
print(f"Max videos: {MAX_VIDEOS}")
print("-" * 50)

class SimpleProgress:
    def progress(self, pct, text=""):
        bar = "█" * int(pct * 30) + "░" * (30 - int(pct * 30))
        print(f"\r[{bar}] {int(pct*100)}% — {text[:60]}", end="", flush=True)

collection, stats = build_index(CHANNEL_URL, MAX_VIDEOS, progress_callback=SimpleProgress())

print(f"\n\n✅ Done!")
print(f"   Channel   : {stats['channel_name']}")
print(f"   Videos    : {stats['videos_indexed']}")
print(f"   Chunks    : {stats['total_chunks']}")
print(f"   Skipped   : {stats['skipped']}")

if stats.get("skipped_titles"):
    print(f"\nSkipped videos (no transcript available):")
    for t in stats["skipped_titles"]:
        print(f"   - {t}")

print(f"\nNow commit the indexes/ folder to GitHub and deploy to Streamlit Cloud.")
