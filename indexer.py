"""
indexer.py  –  Fetch all videos from a YouTube channel and build a ChromaDB index.
"""

import os
import re
import json
import time
from pathlib import Path
from typing import Optional, Callable

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
import chromadb
from chromadb.utils import embedding_functions


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_channel_id(url: str, youtube) -> tuple[str, str]:
    """Return (channel_id, channel_name) from a URL like @handle or /channel/ID."""
    url = url.strip().rstrip("/")

    # Handle @username format
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

    # Handle /channel/UC... format
    channel_match = re.search(r"channel/(UC[\w-]+)", url)
    if channel_match:
        channel_id = channel_match.group(1)
        resp = youtube.channels().list(part="snippet", id=channel_id).execute()
        name = resp["items"][0]["snippet"]["title"]
        return channel_id, name

    raise ValueError("Could not parse channel URL. Use format: https://www.youtube.com/@channelname")


def get_uploads_playlist(channel_id: str, youtube) -> str:
    """Get the 'uploads' playlist ID for a channel."""
    resp = youtube.channels().list(
        part="contentDetails", id=channel_id
    ).execute()
    return resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_all_video_ids(playlist_id: str, youtube, max_videos: int) -> list[dict]:
    """Page through a playlist and collect video IDs + titles."""
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


def fetch_transcript(video_id: str) -> Optional[str]:
    """Fetch transcript text for a video, trying all available options."""
    # Use cookies file if available (helps bypass IP blocks)
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

    ytt = make_api()

    try:
        # Priority 1: fetch English directly
        result = ytt.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(
            chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            for chunk in result.to_raw_data()
        )
    except Exception:
        pass

    try:
        # Priority 2: list all available and take the first one
        transcript_list = ytt.list(video_id)
        for t in transcript_list:
            result = t.fetch()
            return " ".join(
                chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                for chunk in result.to_raw_data()
            )
    except Exception:
        pass

    return None


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping word-level chunks."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


# ── Main build function ────────────────────────────────────────────────────────

def build_index(channel_url: str, max_videos: int = 50,
                progress_callback=None) -> tuple[chromadb.Collection, dict]:
    """
    Fetches all videos from a channel, transcribes them, and builds a ChromaDB index.
    Returns (collection, stats_dict).
    """
    api_key = os.environ["YOUTUBE_API_KEY"]
    youtube = build("youtube", "v3", developerKey=api_key)

    # 1. Resolve channel
    if progress_callback:
        progress_callback.progress(0.05, text="Resolving channel...")
    channel_id, channel_name = extract_channel_id(channel_url, youtube)

    # 2. Get video list
    if progress_callback:
        progress_callback.progress(0.1, text=f"Found channel: {channel_name}. Getting video list...")
    playlist_id = get_uploads_playlist(channel_id, youtube)
    videos = get_all_video_ids(playlist_id, youtube, max_videos)

    # 3. Set up ChromaDB with sentence-transformers (free, local)
    Path("indexes").mkdir(exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", channel_name)[:40]

    client = chromadb.PersistentClient(path=f"indexes/{safe_name}_db")
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    # Delete existing collection if rebuilding
    try:
        client.delete_collection(safe_name)
    except Exception:
        pass
    collection = client.create_collection(safe_name, embedding_function=ef)

    # 4. Fetch transcripts + index
    stats = {
        "channel_name": channel_name,
        "channel_id": channel_id,
        "videos_indexed": 0,
        "skipped": 0,
        "total_chunks": 0,
        "index_name": safe_name,
        "videos": [],
    }

    for i, video in enumerate(videos):
        progress_pct = 0.15 + (0.80 * i / len(videos))
        if progress_callback:
            progress_callback.progress(
                progress_pct,
                text=f"({i+1}/{len(videos)}) Fetching: {video['title'][:50]}..."
            )

        transcript = fetch_transcript(video["id"])
        if not transcript:
            stats["skipped"] += 1
            stats.setdefault("skipped_titles", []).append(video["title"])
            time.sleep(1.0)  # longer pause after skip
            continue

        chunks = chunk_text(transcript)
        ids = [f"{video['id']}_{j}" for j in range(len(chunks))]
        metadatas = [
            {
                "video_id": video["id"],
                "title": video["title"],
                "url": f"https://www.youtube.com/watch?v={video['id']}",
                "chunk_index": j,
            }
            for j in range(len(chunks))
        ]

        # Batch insert (ChromaDB handles up to 5000 at a time)
        collection.add(documents=chunks, ids=ids, metadatas=metadatas)

        stats["videos_indexed"] += 1
        stats["total_chunks"] += len(chunks)
        stats["videos"].append({"id": video["id"], "title": video["title"]})

        time.sleep(0.8)  # Be polite to YouTube's API

    # 5. Save stats
    stats_path = f"indexes/{safe_name}.json"
    with open(stats_path, "w") as f:
        json.dump({"stats": stats, "db_path": f"indexes/{safe_name}_db",
                   "collection_name": safe_name}, f, indent=2)

    if progress_callback:
        progress_callback.progress(1.0, text="Done!")

    return collection, stats


# ── Load existing index ────────────────────────────────────────────────────────

def load_index(json_path: str) -> tuple[chromadb.Collection, dict]:
    """Load a previously built index from its .json metadata file."""
    with open(json_path) as f:
        data = json.load(f)

    stats = data["stats"]
    db_path = data["db_path"]
    collection_name = data["collection_name"]

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_collection(collection_name, embedding_function=ef)

    return collection, stats
