import streamlit as st
import os
import re
from dotenv import load_dotenv
load_dotenv()
import time
import json
from pathlib import Path

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Channel Brain",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Sans:wght@300;400;500&display=swap');
  html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
  h1, h2, h3 { font-family: 'Syne', sans-serif; }
  .stApp { background: #0d0d0d; color: #f0ede6; }
  .block-container { padding-top: 2rem; }
  .stTextInput > div > div > input {
      background: #1a1a1a; border: 1px solid #333; color: #f0ede6; border-radius: 8px;
  }
  .stButton > button {
      background: #e8ff47; color: #0d0d0d; border: none;
      font-family: 'Syne', sans-serif; font-weight: 700;
      border-radius: 8px; padding: 0.5rem 1.5rem;
  }
  .stButton > button:hover { background: #d4eb30; }
  .chat-bubble-user {
      background: #1e1e1e; border-left: 3px solid #e8ff47;
      padding: 12px 16px; border-radius: 8px; margin: 8px 0;
  }
  .chat-bubble-ai {
      background: #161616; border-left: 3px solid #555;
      padding: 12px 16px; border-radius: 8px; margin: 8px 0;
  }
  .source-tag {
      display: inline-block; background: #222; color: #aaa;
      font-size: 11px; padding: 2px 8px; border-radius: 20px; margin: 2px;
  }
  .stat-box {
      background: #1a1a1a; border: 1px solid #2a2a2a;
      border-radius: 10px; padding: 16px; text-align: center;
  }
  .stat-number { font-family: 'Syne', sans-serif; font-size: 2rem; color: #e8ff47; }
  .stat-label { color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
</style>
""", unsafe_allow_html=True)

# ── Imports (with error handling) ─────────────────────────────────────────────
try:
    from indexer import build_index, load_index
    from qa import answer_question
    MODULES_LOADED = True
except ImportError as e:
    MODULES_LOADED = False
    IMPORT_ERROR = str(e)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🎙️ Channel Brain")
    st.markdown("Turn any YouTube channel into a Q&A brain.")
    st.divider()

    st.markdown("### 🔑 API Keys")
    yt_key = st.text_input("YouTube Data API Key", type="password",
                           value=os.getenv("YOUTUBE_API_KEY", ""),
                           help="Get free key at console.cloud.google.com")
    ai_key = st.text_input("Anthropic API Key", type="password",
                           value=os.getenv("ANTHROPIC_API_KEY", ""),
                           help="Get key at console.anthropic.com")

    st.divider()
    st.markdown("### 📺 Index a Channel")
    channel_url = st.text_input("Channel URL",
                                placeholder="https://www.youtube.com/@thekoerneroffice")
    max_videos = st.slider("Max videos to index", 10, 200, 50,
                           help="More videos = longer indexing time")

    index_btn = st.button("⚡ Build Index", use_container_width=True)

    st.divider()
    st.markdown("### 📂 Load Existing Index")
    index_files = list(Path("indexes").glob("*.json")) if Path("indexes").exists() else []
    if index_files:
        selected = st.selectbox("Choose index", [f.stem for f in index_files])
        load_btn = st.button("Load Index", use_container_width=True)
    else:
        st.caption("No indexes saved yet.")
        load_btn = False
        selected = None

    st.divider()
    st.markdown("### 📤 Export Transcripts")
    if st.session_state.get("stats") and st.session_state.get("index"):
        stats = st.session_state.stats
        channel_name = stats.get("channel_name", "channel")
        videos = stats.get("videos", [])
        if videos:
            # Build export text on demand
            if st.button("📄 Generate Export File", use_container_width=True):
                with st.spinner("Building export..."):
                    lines = []
                    lines.append(f"TRANSCRIPT EXPORT: {channel_name}")
                    lines.append(f"Total videos: {len(videos)}")
                    lines.append("=" * 60)
                    lines.append("")

                    collection = st.session_state.index
                    for video in videos:
                        vid_id = video["id"]
                        title = video["title"]
                        url = f"https://www.youtube.com/watch?v={vid_id}"

                        # Pull all chunks for this video from ChromaDB
                        results = collection.get(
                            where={"video_id": vid_id},
                            include=["documents", "metadatas"]
                        )
                        chunks = results.get("documents", [])
                        metadatas = results.get("metadatas", [])

                        # Sort chunks by chunk_index
                        paired = sorted(
                            zip(chunks, metadatas),
                            key=lambda x: x[1].get("chunk_index", 0)
                        )
                        full_text = " ".join(c for c, _ in paired)

                        lines.append(f"TITLE: {title}")
                        lines.append(f"URL: {url}")
                        lines.append("-" * 40)
                        lines.append(full_text)
                        lines.append("")
                        lines.append("=" * 60)
                        lines.append("")

                    export_text = "\n".join(lines)
                    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", channel_name)[:30]
                    st.session_state.export_text = export_text
                    st.session_state.export_filename = f"{safe}_transcripts.txt"

            if st.session_state.get("export_text"):
                st.download_button(
                    label="⬇️ Download .txt File",
                    data=st.session_state.export_text,
                    file_name=st.session_state.export_filename,
                    mime="text/plain",
                    use_container_width=True,
                )
                st.caption(f"Ready: {st.session_state.export_filename}")
        else:
            st.caption("No video data available to export.")
    else:
        st.caption("Load or build an index first.")

# ── Main area ──────────────────────────────────────────────────────────────────
st.markdown("# 🎙️ Channel Brain")
st.markdown("*Ask questions across an entire YouTube channel's content*")

if not MODULES_LOADED:
    st.error(f"Missing dependencies. Run `pip install -r requirements.txt` first.\n\nError: {IMPORT_ERROR}")
    st.stop()

# Session state
if "index" not in st.session_state:
    st.session_state.index = None
if "stats" not in st.session_state:
    st.session_state.stats = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ── Index building ─────────────────────────────────────────────────────────────
if index_btn:
    if not yt_key:
        st.error("Please enter your YouTube API key in the sidebar.")
    elif not channel_url:
        st.error("Please enter a channel URL.")
    else:
        os.environ["YOUTUBE_API_KEY"] = yt_key
        os.environ["ANTHROPIC_API_KEY"] = ai_key

        with st.spinner("🔍 Fetching video list from channel..."):
            progress = st.progress(0, text="Starting...")
            try:
                index, stats = build_index(channel_url, max_videos, progress_callback=progress)
                st.session_state.index = index
                st.session_state.stats = stats
                st.session_state.chat_history = []
                st.success(f"✅ Indexed {stats['videos_indexed']} videos with {stats['total_chunks']} transcript chunks!")
            except Exception as e:
                st.error(f"Error building index: {e}")

# ── Load existing index ────────────────────────────────────────────────────────
if load_btn and selected:
    os.environ["ANTHROPIC_API_KEY"] = ai_key
    with st.spinner("Loading index..."):
        try:
            index, stats = load_index(f"indexes/{selected}.json")
            st.session_state.index = index
            st.session_state.stats = stats
            st.session_state.chat_history = []
            st.success(f"✅ Loaded index: {selected}")
        except Exception as e:
            st.error(f"Error loading index: {e}")

# ── Stats display ──────────────────────────────────────────────────────────────
if st.session_state.stats:
    stats = st.session_state.stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="stat-box"><div class="stat-number">{stats.get("videos_indexed",0)}</div><div class="stat-label">Videos</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-box"><div class="stat-number">{stats.get("total_chunks",0)}</div><div class="stat-label">Chunks</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-box"><div class="stat-number">{stats.get("skipped",0)}</div><div class="stat-label">Skipped</div></div>', unsafe_allow_html=True)
    with col4:
        channel_name = stats.get("channel_name", "—")[:12]
        st.markdown(f'<div class="stat-box"><div class="stat-number" style="font-size:1.1rem">{channel_name}</div><div class="stat-label">Channel</div></div>', unsafe_allow_html=True)
    st.markdown("")

# ── Chat interface ─────────────────────────────────────────────────────────────
if st.session_state.index:
    st.markdown("### 💬 Ask the Channel")

    # Suggested questions
    st.markdown("**Suggested questions:**")
    suggestions = [
        "What are the best side hustle ideas mentioned?",
        "What business types come up most often?",
        "What advice is given for beginners?",
        "Summarize the top 5 recurring themes",
    ]
    cols = st.columns(2)
    for i, s in enumerate(suggestions):
        if cols[i % 2].button(s, key=f"sug_{i}"):
            st.session_state.pending_question = s

    # Chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-bubble-user">🙋 {msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-bubble-ai">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
            if msg.get("sources"):
                for src in msg["sources"][:3]:
                    st.markdown(f'<span class="source-tag">📹 {src}</span>', unsafe_allow_html=True)
                st.markdown("")

    # Input
    question = st.chat_input("Ask anything about this channel's content...")
    if hasattr(st.session_state, "pending_question"):
        question = st.session_state.pending_question
        del st.session_state.pending_question

    if question:
        if not ai_key:
            st.error("Please enter your Anthropic API key to ask questions.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = ai_key
            st.session_state.chat_history.append({"role": "user", "content": question})
            with st.spinner("Thinking..."):
                try:
                    answer, sources = answer_question(question, st.session_state.index)
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources
                    })
                except Exception as e:
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": f"Error: {e}",
                        "sources": []
                    })
            st.rerun()

else:
    # Empty state
    st.markdown("""
    <div style="text-align:center; padding: 60px 20px; color: #555;">
        <div style="font-size: 4rem;">🎙️</div>
        <div style="font-family: 'Syne', sans-serif; font-size: 1.4rem; color: #888; margin-top: 16px;">
            Enter a YouTube channel URL in the sidebar to get started
        </div>
        <div style="color: #444; margin-top: 8px; font-size: 0.9rem;">
            The tool will fetch all transcripts and let you ask questions across the entire catalog
        </div>
    </div>
    """, unsafe_allow_html=True)
