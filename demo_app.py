import streamlit as st
import os
import json
import requests
from dotenv import load_dotenv
load_dotenv()
import time
from pathlib import Path

# ── Zapier webhook ─────────────────────────────────────────────────────────────
def send_lead_to_webhook(email: str, channel: str = "") -> bool:
    """Send lead data to webhook in background thread. Returns True immediately."""
    zapier_url = os.environ.get("ZAPIER_WEBHOOK_URL", "")
    if not zapier_url:
        return False

    payload = {
        "email": email,
        "channel": channel or "Not provided",
        "source": "Channel Brain Demo",
        "demo_channel": "The Koerner Office",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }

    def fire_and_forget():
        try:
            requests.post(zapier_url, json=payload, timeout=15)
        except Exception:
            pass

    import threading
    threading.Thread(target=fire_and_forget, daemon=True).start()
    return True

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Channel Brain — Live Demo",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

*, html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    box-sizing: border-box;
}

.stApp { background: #0a0a0a; color: #f5f0e8; }

/* Disabled buttons — block all mouse interaction, not just visually grey */
.stButton button:disabled,
.stButton button[disabled] {
    pointer-events: none !important;
    opacity: 0.35 !important;
    cursor: not-allowed !important;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 0 !important; max-width: 100% !important; }
section[data-testid="stSidebar"] { display: none; }

/* Suggestion grid — keyed container rendered as 2-column CSS grid */
.st-key-sug_grid > div[data-testid="stVerticalBlock"],
div[class*="st-key-sug_grid"] > div[data-testid="stVerticalBlock"],
div[class*="st-key-sug_grid"][data-testid="stVerticalBlock"] {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 10px !important;
    align-items: start !important;
}
div[class*="st-key-sug_grid"] [data-testid="stElementContainer"] {
    width: 100% !important;
}
div[class*="st-key-sug_grid"] .stButton button {
    height: 100% !important;
}

/* Suggestion button nested columns — force top alignment */
[data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] {
    gap: 12px !important;
    align-items: flex-start !important;
}
[data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] [data-testid="stVerticalBlock"] {
    gap: 12px !important;
}
[data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] [data-testid="stVerticalBlockBorderWrapper"] {
    padding-top: 0 !important;
    margin-top: 0 !important;
}
[data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {
    align-self: flex-start !important;
}
[data-testid="stHorizontalBlock"] {
    gap: 0 !important;
    align-items: flex-start !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child > div:first-child {
    padding: 8px 16px 8px 8px !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {
    background: #080808 !important;
    border-left: 1px solid #1e1e1e !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child > div:first-child {
    padding: 32px 24px 32px 28px !important;
}
/* Fix Ask button width */
.ask-btn > button {
    min-height: 48px !important;
    white-space: nowrap !important;
}

/* Column padding fix — give both columns consistent breathing room */
[data-testid="column"]:first-child > div:first-child {
    padding: 40px 32px 32px 48px !important;
}
[data-testid="column"]:last-child > div:first-child {
    padding: 40px 32px 32px 32px !important;
    border-left: 1px solid #1e1e1e;
    background: #080808;
    min-height: 100vh;
}

/* Hero */
.hero { background: transparent; padding: 16px 64px 8px 56px; position: relative; }
.hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 400px; height: 400px;
    background: radial-gradient(circle, rgba(212,163,89,0.06) 0%, transparent 70%);
    pointer-events: none;
}
.hero-eyebrow {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #d4a359;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.hero-title {
    font-family: 'Playfair Display', serif;
    font-size: clamp(2.8rem, 4.5vw, 3.8rem);
    font-weight: 900;
    line-height: 1.1;
    color: #f5f0e8;
    margin: 0 0 14px;
}
.hero-title span { color: #d4a359; }
.hero-subtitle {
    font-size: 1.08rem;
    color: #aaa;
    font-weight: 400;
    max-width: 620px;
    line-height: 1.7;
    margin-bottom: 20px;
}
.stat-row {
    display: flex;
    gap: 32px;
    flex-wrap: wrap;
    padding: 12px 0;
    border-top: 1px solid #1e1e1e;
    border-bottom: 1px solid #1e1e1e;
    margin-bottom: 0;
}
.stat-item { display: flex; flex-direction: column; }
.stat-num {
    font-family: 'Playfair Display', serif;
    font-size: 2rem;
    font-weight: 700;
    color: #d4a359;
    line-height: 1;
}
.stat-label {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #777;
    margin-top: 6px;
}

/* Chat area */
.chat-label {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #999;
    margin-bottom: 6px;
    margin-top: 12px;
}
.msg-user {
    background: #141414;
    border: 1px solid #2a2a2a;
    border-radius: 2px 16px 16px 16px;
    padding: 14px 18px;
    margin: 12px 0;
    font-size: 0.95rem;
    color: #f5f0e8;
    max-width: 85%;
}
.msg-ai {
    background: #0f0f0f;
    border: 1px solid #1e1e1e;
    border-left: 3px solid #d4a359;
    border-radius: 16px 16px 16px 2px;
    padding: 16px 18px;
    margin: 12px 0 4px;
    font-size: 0.95rem;
    color: #ccc;
    line-height: 1.7;
}
.msg-ai strong { color: #f5f0e8; }
.source-row { margin: 0 0 16px; }
.source-chip {
    display: inline-block;
    background: #141414;
    border: 1px solid #2a2a2a;
    color: #666;
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    padding: 3px 10px;
    border-radius: 20px;
    margin: 2px 3px 2px 0;
}

/* Suggestions */
.suggestions-label {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 10px;
    margin-top: 12px;
}
.stButton > button {
    background: #111 !important;
    border: 1px solid #2a2a2a !important;
    color: #bbb !important;
    border-radius: 8px !important;
    font-size: 0.88rem !important;
    font-family: 'DM Sans', sans-serif !important;
    padding: 12px 16px !important;
    text-align: left !important;
    width: 100% !important;
    transition: all 0.15s ease !important;
    white-space: normal !important;
    height: auto !important;
    line-height: 1.4 !important;
    justify-content: flex-start !important;
}
.stButton > button > div,
.stButton > button > div > p,
.stButton > button p {
    text-align: left !important;
    width: 100% !important;
    justify-content: flex-start !important;
}
.stButton > button:hover {
    background: #1a1a1a !important;
    border-color: #d4a359 !important;
    color: #f5f0e8 !important;
}

/* CTA panel */
.cta-box {
    background: linear-gradient(135deg, #141414 0%, #0f0f0f 100%);
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 14px;
}
.cta-title {
    font-family: 'Playfair Display', serif;
    font-size: 1.2rem;
    color: #f5f0e8;
    margin-bottom: 8px;
}
.cta-body {
    font-size: 0.84rem;
    color: #777;
    line-height: 1.6;
    margin-bottom: 16px;
}
.cta-features {
    list-style: none;
    padding: 0;
    margin: 0 0 10px;
}
.cta-features li {
    font-size: 0.82rem;
    color: #888;
    padding: 2px 0;
}
.cta-features li::before { content: '→ '; color: #d4a359; }

/* Inputs */
.stTextInput > div > div > input {
    background: #1a1a1a !important;
    border: 1px solid #3a3a3a !important;
    border-radius: 8px !important;
    color: #f5f0e8 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.95rem !important;
    padding: 12px 16px !important;
}
.stTextInput > div > div > input:focus {
    border-color: #d4a359 !important;
    box-shadow: 0 0 0 2px rgba(212,163,89,0.1) !important;
}
.stTextInput > div > div > input::placeholder { color: #555 !important; }
.stTextInput label { color: #aaa !important; font-size: 0.84rem !important; }

/* Ask button */
.ask-btn > button {
    background: #d4a359 !important;
    color: #0a0a0a !important;
    border: none !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
}
.ask-btn > button:hover { background: #c4934a !important; }

/* Divider */
.gold-divider {
    border: none;
    border-top: 1px solid #1e1e1e;
    margin: 20px 0;
}

/* Chat scroll */
.chat-scroll {
    max-height: 50vh;
    overflow-y: auto;
    padding-right: 8px;
    scrollbar-width: thin;
    scrollbar-color: #2a2a2a #0a0a0a;
}

/* Toast */
.toast {
    background: #d4a359;
    color: #0a0a0a;
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    text-align: center;
    margin-top: 12px;
}
</style>
""", unsafe_allow_html=True)



# ── Session state ──────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "index" not in st.session_state:
    st.session_state.index = None
if "index_loaded" not in st.session_state:
    st.session_state.index_loaded = False
if "email_submitted" not in st.session_state:
    st.session_state.email_submitted = False
if "loading_started" not in st.session_state:
    st.session_state.loading_started = False
if "generating" not in st.session_state:
    st.session_state.generating = False
if "pending_generation" not in st.session_state:
    st.session_state.pending_generation = None

# ── Load index on startup ──────────────────────────────────────────────────────
CHANNEL_NAME = "The Koerner Office"
CHANNEL_HANDLE = "@thekoerneroffice"
CHANNEL_URL = "https://www.youtube.com/@thekoerneroffice"

@st.cache_resource(show_spinner=False)
def load_demo_index():
    try:
        from indexer import load_index
        # Check Railway volume first, then local indexes folder
        search_paths = ["/data", "indexes"]
        for search_dir in search_paths:
            index_files = list(Path(search_dir).glob("*.json"))
            if index_files:
                index_wrapper, stats = load_index(str(index_files[0]))
                return index_wrapper, stats
    except Exception as e:
        return None, None
    return None, None

# Show branded splash while index loads — only on first load (cache_resource runs once)
splash = st.empty()
splash.markdown("""
<div style="display:flex; flex-direction:column; align-items:center;
            justify-content:center; min-height:100vh; text-align:center;
            padding:40px; background:#0a0a0a;">
    <div style="font-size:5rem; margin-bottom:24px;">🧠</div>
    <div style="font-family:'Playfair Display',Georgia,serif; font-size:2.8rem;
                color:#f5f0e8; margin-bottom:12px; font-weight:700;">
        Channel Brain
    </div>
    <div style="color:#d4a359; font-family:'DM Mono',monospace;
                font-size:12px; letter-spacing:3px; text-transform:uppercase;
                margin-bottom:32px;">
        Loading archive...
    </div>
    <div style="display:flex; gap:12px; align-items:center; justify-content:center;">
        <div style="width:10px; height:10px; border-radius:50%; background:#d4a359;
                    animation:pulse 1.2s infinite;"></div>
        <div style="width:10px; height:10px; border-radius:50%; background:#d4a359;
                    animation:pulse 1.2s 0.4s infinite;"></div>
        <div style="width:10px; height:10px; border-radius:50%; background:#d4a359;
                    animation:pulse 1.2s 0.8s infinite;"></div>
    </div>
</div>
<style>
@keyframes pulse {
    0%, 100% { opacity:0.2; transform:scale(0.8); }
    50% { opacity:1; transform:scale(1.2); }
}
</style>
""", unsafe_allow_html=True)

# Try to load index — cached so only runs once per server session
collection, stats = load_demo_index()

# Clear splash regardless of outcome
splash.empty()

# No index available — show Coming Soon and stop completely
if collection is None:
    st.markdown("""
    <div style="display:flex; flex-direction:column; align-items:center;
                justify-content:center; min-height:100vh; text-align:center;
                padding:40px; background:#0a0a0a;">
        <div style="font-size:4rem; margin-bottom:24px;">🧠</div>
        <div style="font-family:'Playfair Display',serif; font-size:2rem;
                    color:#f5f0e8; margin-bottom:16px;">
            Channel Brain
        </div>
        <div style="color:#d4a359; font-family:'DM Mono',monospace;
                    font-size:12px; letter-spacing:3px; text-transform:uppercase;
                    margin-bottom:24px;">
            Coming Soon
        </div>
        <div style="color:#666; font-size:0.95rem; max-width:420px; line-height:1.7;">
            The demo archive is being prepared.<br>
            Check back shortly.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# Index loaded successfully — store in session state and continue
st.session_state.index = collection
st.session_state.index_loaded = True
st.session_state.stats = stats

# ── Stats ──────────────────────────────────────────────────────────────────────
stats = st.session_state.get("stats", {})
videos_count = stats.get("videos_indexed", "95") if stats else "95"
chunks_count = stats.get("total_chunks", "1,445") if stats else "1,445"

# ── MAIN LAYOUT — columns start from very top ──────────────────────────────────
left_col, right_col = st.columns([3, 1])

with left_col:
    # Hero
    st.markdown(f"""
    <div class="hero">
        <div class="hero-eyebrow"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#d4a359;margin-right:8px;vertical-align:middle;"></span>Channel Brain — Live Demo</div>
        <h1 class="hero-title">This is what<br><span>your channel</span><br>could look like.</h1>
        <p class="hero-subtitle">
            Channel Brain turns any YouTube archive into an AI assistant your audience
            can have a conversation with. Below is a working example built on
            <strong style="color:#f5f0e8;">The Koerner Office</strong> — a small business podcast
            we indexed to show you exactly how it works.
        </p>
        <div class="stat-row">
            <div class="stat-item">
                <span class="stat-num">{videos_count}</span>
                <span class="stat-label">Episodes indexed</span>
            </div>
            <div class="stat-item">
                <span class="stat-num">{chunks_count if isinstance(chunks_count, str) else f"{chunks_count:,}"}</span>
                <span class="stat-label">Transcript chunks</span>
            </div>
            <div class="stat-item">
                <span class="stat-num">~1 wk</span>
                <span class="stat-label">To build yours</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="chat-label" style="padding-left:56px;">Try it — ask the Koerner Office archive anything</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="margin-bottom: 20px; padding-left:56px;">
        <a href="{CHANNEL_URL}" target="_blank"
           style="color:#d4a359; font-size:0.82rem; font-family:'DM Mono',monospace;
                  text-decoration:none; letter-spacing:1px;">
            → Browse The Koerner Office on YouTube ↗
        </a>
    </div>
    """, unsafe_allow_html=True)

    # Suggested questions
    suggestions = [
        "What are the best low-investment side hustle ideas mentioned across all episodes?",
        "Which episodes cover e-commerce or Amazon FBA businesses?",
        "What advice does Chris give most often to beginners starting a business?",
        "What are the most profitable service businesses discussed on the show?",
        "Which guests built businesses from zero with no outside funding?",
        "What are the best examples of turning a skill into a business?",
    ]

    # Track generating state for button disabling
    is_generating = st.session_state.get("generating", False)

    if not st.session_state.chat_history:
        st.markdown('<div class="suggestions-label" style="padding-left:8px;">Try asking</div>', unsafe_allow_html=True)
        # Keyed container — CSS turns its inner vertical block into a 2-col grid
        with st.container(key="sug_grid"):
            for i, s in enumerate(suggestions):
                if st.button(s, key=f"sug_{i}", use_container_width=True, disabled=is_generating):
                    st.session_state.pending_q = s

    # Chat history
    if st.session_state.chat_history:
        chat_html = '<div class="chat-scroll">'
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                chat_html += f'<div class="msg-user">🙋 {msg["content"]}</div>'
            else:
                if msg["content"] == "CAP_REACHED":
                    chat_html += f'''<div class="msg-ai" style="border-left-color:#888; text-align:center; padding:20px;">
                        <div style="font-size:1.3rem; margin-bottom:8px;">🧠</div>
                        <div style="color:#f5f0e8; font-weight:600; margin-bottom:6px;">The archive is resting for this month.</div>
                        <div style="color:#888; font-size:0.85rem; margin-bottom:12px;">Resets on the 1st of next month.</div>
                        <a href="{CHANNEL_URL}" target="_blank" style="background:#d4a359; color:#0a0a0a; padding:8px 20px; border-radius:6px; text-decoration:none; font-weight:600; font-size:0.85rem;">Browse {CHANNEL_NAME} on YouTube →</a>
                    </div>'''
                else:
                    content = msg["content"].replace("\n", "<br>")
                    chat_html += f'<div class="msg-ai">{content}</div>'
                    if msg.get("sources"):
                        chips = "".join(
                            f'<span class="source-chip">📹 {s[:45]}{"…" if len(s)>45 else ""}</span>'
                            for s in msg["sources"][:4]
                        )
                        chat_html += f'<div class="source-row">{chips}</div>'
        chat_html += '</div>'
        st.markdown(chat_html, unsafe_allow_html=True)

        # More suggestions after first answer
        if len(st.session_state.chat_history) >= 2:
            st.markdown('<br><div class="suggestions-label">Keep exploring</div>', unsafe_allow_html=True)
            asked = [m["content"] for m in st.session_state.chat_history if m["role"] == "user"]
            more = [s for s in suggestions if s not in asked]
            cols2 = st.columns(2)
            for i, s in enumerate(more[:4]):
                if cols2[i % 2].button(s, key=f"more_{i}", disabled=is_generating):
                    st.session_state.pending_q = s

    # Input row
    q_col, btn_col = st.columns([6, 1])
    with q_col:
        question = st.text_input(
            "question",
            label_visibility="collapsed",
            placeholder="Ask anything about The Koerner Office episodes...",
            key="question_input"
        )
    with btn_col:
        st.markdown('<div class="ask-btn">', unsafe_allow_html=True)
        ask_btn = st.button("Ask →", use_container_width=True, disabled=is_generating)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Handle input — if already generating, ONLY honor the original question.
    # This prevents a second click (which may slip through during the network
    # round-trip before disabled buttons render) from hijacking the in-flight request.
    final_q = None
    if st.session_state.get("generating", False):
        # Discard any stray click that landed during generation
        if hasattr(st.session_state, "pending_q"):
            del st.session_state.pending_q
        final_q = st.session_state.get("pending_generation")
    elif ask_btn and question:
        final_q = question
    elif hasattr(st.session_state, "pending_q"):
        final_q = st.session_state.pending_q
        del st.session_state.pending_q

    if final_q:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            st.error("Anthropic API key not configured. Add it to Streamlit secrets.")
        elif not st.session_state.index:
            st.warning("Index not loaded yet. Please wait a moment and try again.")
        else:
            # ── Phase 1: set generating flag, rerun to disable buttons ────────
            if not st.session_state.get("generating", False):
                st.session_state.generating = True
                st.session_state.pending_generation = final_q
                st.session_state.chat_history.append({"role": "user", "content": final_q})
                st.rerun()

            # ── Phase 2: buttons already disabled, now run the API call ───────
            else:
                # Do NOT clear pending_generation here. If this script run gets
                # interrupted by a stray click before finishing, the next run
                # must still be able to resume the ORIGINAL question. Only the
                # finally block (after success or failure) clears it.

                # Branded animated thinking state
                thinking = st.empty()
                thinking.markdown(f"""
                <div style="display:flex; align-items:flex-start; gap:12px; margin:12px 0;">
                    <div style="font-size:1.2rem; margin-top:2px;">🧠</div>
                    <div style="background:#1a1a1a; border-left:3px solid #d4a359;
                                border-radius:0 8px 8px 0; padding:16px 20px;
                                display:flex; align-items:center; gap:16px;">
                        <div style="color:#888; font-size:0.85rem; font-family:'DM Mono',monospace;
                                    letter-spacing:1px; text-transform:uppercase;">
                            Searching the archive
                        </div>
                        <div style="display:flex; gap:6px; align-items:center;">
                            <div style="width:7px; height:7px; border-radius:50%;
                                        background:#d4a359; animation:tpulse 1.2s infinite;"></div>
                            <div style="width:7px; height:7px; border-radius:50%;
                                        background:#d4a359; animation:tpulse 1.2s 0.4s infinite;"></div>
                            <div style="width:7px; height:7px; border-radius:50%;
                                        background:#d4a359; animation:tpulse 1.2s 0.8s infinite;"></div>
                        </div>
                    </div>
                </div>
                <style>
                @keyframes tpulse {{
                    0%, 100% {{ opacity:0.2; transform:scale(0.7); }}
                    50% {{ opacity:1; transform:scale(1.1); }}
                }}
                </style>
                """, unsafe_allow_html=True)

                try:
                    from qa import answer_question
                    os.environ["ANTHROPIC_API_KEY"] = anthropic_key
                    answer, sources = answer_question(final_q, st.session_state.index, client_id="koerner-office")

                    if answer == "CAP_REACHED":
                        # Show cap message immediately in placeholder
                        thinking.markdown(f"""
                        <div class="msg-ai" style="border-left-color:#888; text-align:center; padding:20px;">
                            <div style="font-size:1.3rem; margin-bottom:8px;">🧠</div>
                            <div style="color:#f5f0e8; font-weight:600; margin-bottom:6px;">The archive is resting for this month.</div>
                            <div style="color:#888; font-size:0.85rem; margin-bottom:12px;">Resets on the 1st of next month.</div>
                            <a href="{CHANNEL_URL}" target="_blank" style="background:#d4a359; color:#0a0a0a; padding:8px 20px;
                               border-radius:6px; text-decoration:none; font-weight:600; font-size:0.85rem;">
                               Browse {CHANNEL_NAME} on YouTube →</a>
                        </div>
                        """, unsafe_allow_html=True)
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": "CAP_REACHED",
                            "sources": [],
                        })
                    else:
                        # Render answer immediately — eliminates blank gap before rerun
                        content = answer.replace("\n", "<br>")
                        thinking.markdown(f"""
                        <div class="chat-scroll">
                            <div class="msg-ai">{content}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": answer,
                            "sources": sources,
                        })

                except Exception as e:
                    thinking.empty()
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": f"Something went wrong: {e}",
                        "sources": [],
                    })
                finally:
                    # Always clear generating flag — buttons re-enable on next render
                    st.session_state.generating = False
                    st.session_state.pending_generation = None
                    # Discard any suggestion clicks that slipped through during generation
                    if hasattr(st.session_state, "pending_q"):
                        del st.session_state.pending_q

                st.rerun()

# ── RIGHT PANEL ────────────────────────────────────────────────────────────────
with right_col:

    # All static right panel HTML in one render call — faster than 7 separate calls
    st.markdown("""
    <div style="text-align:center; padding: 24px 0 20px;">
        <div style="font-size:3rem; margin-bottom:10px;">🧠</div>
        <div style="font-family:Georgia,serif; font-size:1.5rem;
                    color:#f5f0e8; font-weight:700; margin-bottom:6px;">
            Channel Brain
        </div>
        <div style="font-family:monospace; font-size:10px;
                    letter-spacing:3px; color:#d4a359; text-transform:uppercase;">
            Turn your archive into an AI
        </div>
    </div>
    <hr style="border:none; border-top:1px solid #1e1e1e; margin: 0 0 20px;">
    <div style="display:flex; align-items:flex-start; gap:14px; padding:14px 0;">
        <div style="min-width:36px; height:36px; border-radius:50%; background:#d4a359;
                    color:#0a0a0a; font-weight:700; font-size:0.85rem; display:flex;
                    align-items:center; justify-content:center; flex-shrink:0;">1</div>
        <div>
            <div style="color:#f5f0e8; font-size:0.88rem; font-weight:600; margin-bottom:4px;">
                We index your channel</div>
            <div style="color:#888; font-size:0.78rem; line-height:1.5;">
                Every video transcript is pulled, chunked, and stored in a searchable database.</div>
        </div>
    </div>
    <hr style="border:none; border-top:1px solid #1a1a1a; margin:0;">
    <div style="display:flex; align-items:flex-start; gap:14px; padding:14px 0;">
        <div style="min-width:36px; height:36px; border-radius:50%; background:#d4a359;
                    color:#0a0a0a; font-weight:700; font-size:0.85rem; display:flex;
                    align-items:center; justify-content:center; flex-shrink:0;">2</div>
        <div>
            <div style="color:#f5f0e8; font-size:0.88rem; font-weight:600; margin-bottom:4px;">
                Your audience asks questions</div>
            <div style="color:#888; font-size:0.78rem; line-height:1.5;">
                They type any question in plain English, just like texting you directly.</div>
        </div>
    </div>
    <hr style="border:none; border-top:1px solid #1a1a1a; margin:0;">
    <div style="display:flex; align-items:flex-start; gap:14px; padding:14px 0;">
        <div style="min-width:36px; height:36px; border-radius:50%; background:#d4a359;
                    color:#0a0a0a; font-weight:700; font-size:0.85rem; display:flex;
                    align-items:center; justify-content:center; flex-shrink:0;">3</div>
        <div>
            <div style="color:#f5f0e8; font-size:0.88rem; font-weight:600; margin-bottom:4px;">
                AI answers from your content</div>
            <div style="color:#888; font-size:0.78rem; line-height:1.5;">
                Answers sourced only from your videos, with links back to the source episode.</div>
        </div>
    </div>
    <hr style="border:none; border-top:1px solid #1e1e1e; margin:0 0 24px;">
    <div class="cta-box">
        <div class="cta-title">Want Channel Brain for your channel?</div>
        <p class="cta-body">
            What you just tried? We build that for your channel.
            Trained on your content, branded for your audience,
            live on your website in under a week.
        </p>
        <ul class="cta-features">
            <li>We index your full video catalog</li>
            <li>Answers come only from your content</li>
            <li>Embed it on your site or membership</li>
            <li>Live in under a week</li>
            <li>Zero work on your end</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Email capture
    if not st.session_state.email_submitted:
        email = st.text_input(
            "Your email",
            placeholder="your@email.com",
            label_visibility="visible",
            key="email_capture"
        )
        channel_name_input = st.text_input(
            "Your channel name (optional)",
            placeholder="e.g. My Lawn Care Channel",
            label_visibility="visible",
            key="channel_name_input"
        )
        st.markdown('<div class="ask-btn">', unsafe_allow_html=True)
        if st.button("Request a Demo for My Channel →", use_container_width=True):
            if email and "@" in email:
                success = send_lead_to_webhook(email, channel_name_input)
                if success:
                    st.session_state.email_submitted = True
                    st.rerun()
                else:
                    # Fallback — save locally if Zapier fails
                    leads_file = Path("leads.json")
                    leads = json.loads(leads_file.read_text()) if leads_file.exists() else []
                    leads.append({
                        "email": email,
                        "channel": channel_name_input,
                        "timestamp": time.time()
                    })
                    leads_file.write_text(json.dumps(leads, indent=2))
                    st.session_state.email_submitted = True
                    st.rerun()
            else:
                st.error("Please enter a valid email address.")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="toast">
            ✓ Got it! We'll be in touch within 24 hours.
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <hr class="gold-divider">
    <div style="font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 2px;
                text-transform: uppercase; color: #444; margin-bottom: 14px;">
        About this demo
    </div>
    <div style="font-size: 0.82rem; color: #666; line-height: 1.7;">
        This is a <strong style="color:#888;">Channel Brain demo</strong> built on
        <strong style="color: #888;">The Koerner Office</strong> — a small business
        podcast by Chris Koerner. We indexed it as an example to show creators
        what Channel Brain can do for their own channel.<br><br>
        <strong style="color:#888;">This is not affiliated with or endorsed
        by The Koerner Office.</strong><br><br>
        <a href="{CHANNEL_URL}" target="_blank"
           style="color: #d4a359; text-decoration: none;">
            → Visit The Koerner Office ↗
        </a>
    </div>
    </div>
    """, unsafe_allow_html=True)
