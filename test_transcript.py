"""
test_transcript.py - Diagnose transcript availability using new API syntax.
Usage: python test_transcript.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]

print("Step 1: Fetching video IDs from The Koerner Office...")
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

channel_resp = youtube.search().list(
    part="snippet", q="thekoerneroffice", type="channel", maxResults=1
).execute()
channel_id = channel_resp["items"][0]["snippet"]["channelId"]

playlist_resp = youtube.channels().list(
    part="contentDetails", id=channel_id
).execute()
playlist_id = playlist_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

videos_resp = youtube.playlistItems().list(
    part="snippet", playlistId=playlist_id, maxResults=3
).execute()

# Use cookies if available
from pathlib import Path
cookies_path = Path("cookies.txt")
if cookies_path.exists():
    print("✅ cookies.txt found — using browser cookies to bypass IP block")
    import http.cookiejar, requests as req_session
    jar = http.cookiejar.MozillaCookieJar()
    jar.load(str(cookies_path), ignore_discard=True, ignore_expires=True)
    session = req_session.Session()
    session.cookies = jar
    ytt = YouTubeTranscriptApi(http_client=session)
else:
    print("⚠️  No cookies.txt found — running without cookies")
    ytt = YouTubeTranscriptApi()

for item in videos_resp["items"]:
    vid_id = item["snippet"]["resourceId"]["videoId"]
    title = item["snippet"]["title"]
    print(f"\n{'='*60}")
    print(f"Video : {title}")
    print(f"ID    : {vid_id}")

    # Check available transcripts
    print("Step 2: Listing available transcripts...")
    try:
        transcript_list = ytt.list(vid_id)
        for t in transcript_list:
            print(f"  - {t.language} ({t.language_code}) | "
                  f"Auto-generated: {t.is_generated}")
    except Exception as e:
        print(f"  ❌ list() failed: {e}")

    # Try fetching
    print("Step 3: Fetching transcript...")
    try:
        result = ytt.fetch(vid_id, languages=["en", "en-US", "en-GB"])
        raw = result.to_raw_data()
        text = " ".join(c.get("text","") for c in raw[:5])
        print(f"  ✅ SUCCESS — First 200 chars: {text[:200]}")
    except Exception as e:
        print(f"  ❌ fetch() failed: {e}")
        # Try fallback
        try:
            transcript_list = ytt.list(vid_id)
            for t in transcript_list:
                result = t.fetch()
                raw = result.to_raw_data()
                text = " ".join(c.get("text","") for c in raw[:5])
                print(f"  ✅ FALLBACK SUCCESS ({t.language}): {text[:200]}")
                break
        except Exception as e2:
            print(f"  ❌ Fallback also failed: {e2}")

print("\n" + "="*60)
print("Done.")
