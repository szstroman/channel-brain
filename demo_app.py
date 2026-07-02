import streamlit as st
import os
import json
import requests
from dotenv import load_dotenv
load_dotenv()
import time
from pathlib import Path

# ── Background scheduler for weekly sync ──────────────────────────────────────
# Runs sync_runner.main() in a background thread on a weekly schedule.
# Uses APScheduler (mature Python lib).
#
# IMPORTANT: Streamlit re-executes this whole script on every user interaction,
# so we can't just do `if not FLAG: start(); FLAG = True` — the FLAG=False line
# at the top would reset it every rerun. Instead we stash the "started" state
# on the sys.modules['streamlit'] object itself, which persists across reruns
# because it's the actual imported module singleton in the Python process.
#
# NOTE: Assumes single Streamlit replica. If Railway ever runs multiple replicas
# of this service, we'd get one sync-runner per replica firing at the same time.
# For weekly cadence with 1 replica that's fine — document if we ever scale up.

def _start_sync_scheduler():
    """Start APScheduler background thread. Runs sync_runner weekly.
    Never raises — a broken scheduler must not take down the demo.
    Logs to stderr with explicit flush so Railway captures output regardless
    of how Streamlit buffers stdout."""
    import sys
    streamlit_mod = sys.modules.get("streamlit")
    # Stash the flag on the streamlit module singleton — persists across reruns
    if getattr(streamlit_mod, "_cb_scheduler_started", False):
        return  # Already started for this Python process — don't spawn duplicates

    def _log(msg):
        """Log to stderr with flush — bypasses Streamlit's stdout buffering."""
        print(msg, file=sys.stderr, flush=True)

    # Set the guard EARLY so any exit path (success, import error, start error)
    # prevents re-attempts on every Streamlit rerun. Otherwise we'd spam logs
    # and waste CPU retrying failed imports/starts on every user interaction.
    try:
        streamlit_mod._cb_scheduler_started = True
    except (AttributeError, TypeError):
        # Extremely unlikely — streamlit somehow rejects attribute setting.
        # We continue without the guard; worst case is duplicate warnings.
        pass

    _log("[scheduler] initializing background sync...")

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as e:
        # apscheduler not installed — silent skip (local dev without deps).
        # Prints once because the guard flag was set above.
        _log(f"[scheduler] apscheduler not installed ({e}), skipping background sync")
        return

    def _run_sync_job():
        """Wrapper that invokes sync_runner with error isolation."""
        _log("[scheduler] weekly sync starting...")
        try:
            import sync_runner
            # sync_runner.main() reads sys.argv for args — set it to just the
            # script name so it processes all active clients with no flags
            original_argv = sys.argv
            sys.argv = ["sync_runner.py"]
            try:
                exit_code = sync_runner.main()
                _log(f"[scheduler] weekly sync finished with exit code {exit_code}")
            finally:
                sys.argv = original_argv
        except Exception as e:
            # Never let a sync error kill the Streamlit process
            _log(f"[scheduler] weekly sync FAILED with exception: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)

    # Wrap scheduler construction AND .start() in try/except.
    # APScheduler can raise at start time in unusual environments (signal
    # handler conflicts, thread creation failures). If it does, the demo
    # must continue working — sync automation is strictly additive.
    try:
        scheduler = BackgroundScheduler(timezone="UTC")
        # Every Monday at 09:00 UTC
        scheduler.add_job(
            _run_sync_job,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="weekly_sync",
            replace_existing=True,
        )
        scheduler.start()
    except Exception as e:
        # Broken scheduler must NEVER crash the demo. Log and continue.
        _log(f"[scheduler] FAILED to start scheduler: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return

    _log("[scheduler] background sync scheduler started (weekly, Mon 09:00 UTC)")

# Start the scheduler now. Idempotent — safe to call on every Streamlit rerun.
# Wrapped in try/except at the call site as a last-resort belt-and-suspenders:
# even if _start_sync_scheduler somehow raises despite its own internal handlers,
# the demo must still load.
try:
    _start_sync_scheduler()
except Exception as _e:
    import sys as _sys
    print(f"[scheduler] top-level failure: {type(_e).__name__}: {_e}",
          file=_sys.stderr, flush=True)

# ── Multi-tenant client resolution ─────────────────────────────────────────────
# Resolve which client this session is viewing based on the ?client= URL param.
# This must run BEFORE any other UI code so hardcoded constants can be replaced
# with client-specific values.
from clients_config import get_client

# Streamlit's query_params returns dict-like; .get() safely handles missing key
_requested_client = st.query_params.get("client")
_client_id, _client_data, _client_status = get_client(_requested_client)

# These become the "current session's client" values used everywhere below
CURRENT_CLIENT_ID = _client_id
CURRENT_CLIENT = _client_data
CURRENT_CLIENT_STATUS = _client_status  # "ok" | "inactive" | "fallback" | "default"

# ── Zapier webhook ─────────────────────────────────────────────────────────────
def send_lead_to_webhook(email: str, channel: str = "", demo_channel: str = "") -> bool:
    """Send lead data to webhook in background thread. Returns True immediately."""
    zapier_url = os.environ.get("ZAPIER_WEBHOOK_URL", "")
    if not zapier_url:
        return False

    payload = {
        "email": email,
        "channel": channel or "Not provided",
        "source": "Channel Brain Demo",
        "demo_channel": demo_channel or "Unknown",
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
    text-decoration: none;
    transition: all 0.15s ease;
}
a.source-chip:hover {
    background: #1f1f1f;
    border-color: #d4a359;
    color: #d4a359;
    cursor: pointer;
}
a.source-chip:visited {
    color: #666;
}
a.source-chip:visited:hover {
    color: #d4a359;
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



# ── Session state (per-client namespacing) ────────────────────────────────────
# Each piece of client-specific state gets stored under a key that includes
# the current client_id, so switching ?client= in the same browser tab doesn't
# leak chat history / index / lead capture between clients.
#
# Usage:
#   ck("chat_history")   # → "chat_history__koerner-office"
#   st.session_state[ck("chat_history")].append(...)
#
# The ss_get / ss_set / ss_has helpers wrap this pattern so we don't have to
# repeat the prefix logic everywhere.
def ck(key: str) -> str:
    """Client-scoped session state key. Prefixes key with current client_id."""
    return f"{key}__{CURRENT_CLIENT_ID}"

def ss_get(key: str, default=None):
    """Get a client-scoped session state value, returning default if missing."""
    return st.session_state.get(ck(key), default)

def ss_set(key: str, value):
    """Set a client-scoped session state value."""
    st.session_state[ck(key)] = value

def ss_has(key: str) -> bool:
    """Check if a client-scoped session state key exists."""
    return ck(key) in st.session_state

def ss_del(key: str):
    """Delete a client-scoped session state key if it exists."""
    if ss_has(key):
        del st.session_state[ck(key)]

# Initialize per-client state on first access for this (session, client) pair
if not ss_has("chat_history"):
    ss_set("chat_history", [])
if not ss_has("index"):
    ss_set("index", None)
if not ss_has("index_loaded"):
    ss_set("index_loaded", False)
if not ss_has("email_submitted"):
    ss_set("email_submitted", False)
if not ss_has("generating"):
    ss_set("generating", False)
if not ss_has("pending_generation"):
    ss_set("pending_generation", None)

# loading_started stays global — it's just a splash-screen flag, not client-specific
if "loading_started" not in st.session_state:
    st.session_state.loading_started = False

# ── Load index on startup ──────────────────────────────────────────────────────
# These constants now derive from the resolved client rather than hardcoded values.
# For the default client (koerner-office), values are identical to before.
CHANNEL_NAME = CURRENT_CLIENT["channel_name"]
CHANNEL_HANDLE = CURRENT_CLIENT["channel_handle"]
CHANNEL_URL = CURRENT_CLIENT["channel_url"]
CREATOR_NAME = CURRENT_CLIENT["creator_name"]

# ── Bootstrap: seed /data volume from repo on first startup ───────────────────
# When deployed to Railway, the /data volume starts empty. If we have bootstrap
# files committed to the repo at /bootstrap/, copy them to /data/ on first run.
# After the first copy, /data/ persists across deploys so we never copy again.
def bootstrap_data_volume():
    import shutil
    bootstrap_dir = Path("bootstrap")
    if not bootstrap_dir.exists():
        return  # No bootstrap folder, nothing to do (e.g. local dev)

    target_dir = Path("/data")
    try:
        target_dir.mkdir(exist_ok=True)
    except Exception:
        return  # Can't write to /data (e.g. local dev without /data folder)

    for src in bootstrap_dir.glob("*.json"):
        dest = target_dir / src.name
        if not dest.exists():
            try:
                shutil.copy2(src, dest)
            except Exception:
                pass  # Fail silently — app will fall back to Coming Soon

bootstrap_data_volume()

@st.cache_resource(show_spinner=False)
def load_demo_index(client_id: str):
    """
    Load the index file for a specific client. Cached per-client so that
    switching ?client= in the URL doesn't reload the same index repeatedly
    but does correctly load each client's own index.

    Looks for {client_id}.json specifically, not just any *.json file, so
    that clients.json or other config files can't accidentally be treated
    as an index.
    """
    try:
        from indexer import load_index
        # Look for the client's specific index file
        expected_filename = f"{client_id}.json"
        search_paths = ["/data", "indexes"]
        for search_dir in search_paths:
            candidate = Path(search_dir) / expected_filename
            if candidate.exists() and candidate.is_file():
                index_wrapper, stats = load_index(str(candidate))
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

# ── Inactive client check ─────────────────────────────────────────────────────
# If a client is deactivated (e.g., non-payment, offboarded), show a polite
# "no longer available" page instead of loading their index. This protects the
# creator's brand — visitors don't see "wrong" content and don't get an error.
if CURRENT_CLIENT_STATUS == "inactive":
    splash.empty()
    st.markdown(f"""
    <div style="display:flex; flex-direction:column; align-items:center;
                justify-content:center; min-height:80vh; text-align:center;
                padding:40px;">
        <div style="font-size:4rem; margin-bottom:20px;">🧠</div>
        <div style="font-family:Georgia,serif; font-size:2.2rem; color:#f5f0e8;
                    margin-bottom:12px; font-weight:700;">
            Channel Brain
        </div>
        <div style="color:#d4a359; font-family:'DM Mono',monospace; font-size:11px;
                    letter-spacing:3px; text-transform:uppercase; margin-bottom:32px;">
            No longer available
        </div>
        <div style="max-width:520px; color:#999; font-size:0.95rem; line-height:1.7;">
            This Channel Brain is no longer active. If you're looking for the creator's
            content directly, please visit their YouTube channel or website.
        </div>
        <div style="margin-top:36px;">
            <a href="https://channel-brain-production.up.railway.app"
               style="color:#d4a359; text-decoration:none; font-family:'DM Mono',monospace;
                      font-size:10px; letter-spacing:2px; text-transform:uppercase;">
                → View the Channel Brain demo ↗
            </a>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# Try to load index — cached per-client so only runs once per (server, client) pair
collection, stats = load_demo_index(CURRENT_CLIENT_ID)

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
ss_set("index", collection)
ss_set("index_loaded", True)
ss_set("stats", stats)

# ── Stats ──────────────────────────────────────────────────────────────────────
stats = ss_get("stats", {})
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
            <strong style="color:#f5f0e8;">{CHANNEL_NAME}</strong> —
            a channel we indexed to show you exactly how it works.
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

    st.markdown(f'<div class="chat-label" style="padding-left:56px;">Try it — ask the {CHANNEL_NAME} archive anything</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="margin-bottom: 20px; padding-left:56px;">
        <a href="{CHANNEL_URL}" target="_blank"
           style="color:#d4a359; font-size:0.82rem; font-family:'DM Mono',monospace;
                  text-decoration:none; letter-spacing:1px;">
            → Browse {CHANNEL_NAME} on YouTube ↗
        </a>
    </div>
    """, unsafe_allow_html=True)

    # Suggested questions
    # NOTE: These are hardcoded for the default Koerner Office demo. When we add
    # niche demos (e.g., real estate creator), each client's suggestions should
    # come from clients.json. For R2-07 this is left as-is since the default
    # client is currently the only client.
    suggestions = [
        "What are Chris' favorite business ideas of all time?",
        "What does Chris say about starting a business with little money?",
        "What are the most common pieces of advice Chris gives entrepreneurs?",
        "What are Chris' top thoughts on service businesses like pressure washing?",
        "What has Chris said about real estate and RV park investing?",
        "What is Chris' best advice for someone just getting started?",
    ]

    # Track generating state for button disabling
    is_generating = ss_get("generating", False)

    if not ss_get("chat_history"):
        st.markdown('<div class="suggestions-label" style="padding-left:8px;">Try asking</div>', unsafe_allow_html=True)
        # Keyed container — CSS turns its inner vertical block into a 2-col grid
        with st.container(key="sug_grid"):
            for i, s in enumerate(suggestions):
                if st.button(s, key=f"sug_{i}", use_container_width=True, disabled=is_generating):
                    ss_set("pending_q", s)

    # Chat history
    if ss_get("chat_history"):
        chat_html = '<div class="chat-scroll">'
        for msg in ss_get("chat_history"):
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
                        chip_parts = []
                        for s in msg["sources"][:4]:
                            # Support both old format (string) and new format (dict)
                            if isinstance(s, dict):
                                title = s.get("title", "Unknown")
                                url = s.get("url", "")
                            else:
                                title = str(s)
                                url = ""
                            label = f'📹 {title[:45]}{"…" if len(title)>45 else ""}'
                            if url:
                                chip_parts.append(
                                    f'<a href="{url}" target="_blank" rel="noopener" class="source-chip">{label}</a>'
                                )
                            else:
                                chip_parts.append(f'<span class="source-chip">{label}</span>')
                        chips = "".join(chip_parts)
                        chat_html += f'<div class="source-row">{chips}</div>'
        chat_html += '</div>'
        st.markdown(chat_html, unsafe_allow_html=True)

        # More suggestions after first answer
        if len(ss_get("chat_history")) >= 2:
            st.markdown('<br><div class="suggestions-label">Keep exploring</div>', unsafe_allow_html=True)
            asked = [m["content"] for m in ss_get("chat_history") if m["role"] == "user"]
            more = [s for s in suggestions if s not in asked]
            cols2 = st.columns(2)
            for i, s in enumerate(more[:4]):
                if cols2[i % 2].button(s, key=f"more_{i}", disabled=is_generating):
                    ss_set("pending_q", s)

    # Input row
    q_col, btn_col = st.columns([6, 1])
    with q_col:
        question = st.text_input(
            "question",
            label_visibility="collapsed",
            placeholder=f"Ask anything about {CHANNEL_NAME} episodes...",
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
    if ss_get("generating", False):
        # Discard any stray click that landed during generation
        if ss_has("pending_q"):
            ss_del("pending_q")
        final_q = ss_get("pending_generation")
    elif ask_btn and question:
        final_q = question
    elif ss_has("pending_q"):
        final_q = ss_get("pending_q")
        ss_del("pending_q")

    if final_q:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            st.error("Anthropic API key not configured. Add it to Streamlit secrets.")
        elif not ss_get("index"):
            st.warning("Index not loaded yet. Please wait a moment and try again.")
        else:
            # ── Phase 1: set generating flag, rerun to disable buttons ────────
            if not ss_get("generating", False):
                ss_set("generating", True)
                ss_set("pending_generation", final_q)
                ss_get("chat_history").append({"role": "user", "content": final_q})
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
                    answer, sources = answer_question(final_q, ss_get("index"), client_id=CURRENT_CLIENT["namespace"])

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
                        ss_get("chat_history").append({
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
                        ss_get("chat_history").append({
                            "role": "assistant",
                            "content": answer,
                            "sources": sources,
                        })

                except Exception as e:
                    thinking.empty()
                    ss_get("chat_history").append({
                        "role": "assistant",
                        "content": f"Something went wrong: {e}",
                        "sources": [],
                    })
                finally:
                    # Always clear generating flag — buttons re-enable on next render
                    ss_set("generating", False)
                    ss_set("pending_generation", None)
                    # Discard any suggestion clicks that slipped through during generation
                    if ss_has("pending_q"):
                        ss_del("pending_q")

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

    <!-- Creator Mode value prop reveal -->
    <div style="background: linear-gradient(135deg, #1a1410 0%, #14110a 100%);
                border-left: 3px solid #d4a359;
                border-radius: 0 6px 6px 0;
                padding: 18px 18px 16px;
                margin: 0 0 24px;">
        <div style="color:#d4a359; font-family:'DM Mono',monospace;
                    font-size:10px; letter-spacing:2px; text-transform:uppercase;
                    margin-bottom:8px;">
            Plus — for you
        </div>
        <div style="color:#f5f0e8; font-family:Georgia,serif;
                    font-size:1.05rem; font-weight:600; line-height:1.35;
                    margin-bottom:10px;">
            Your archive becomes a tool you can use, too
        </div>
        <div style="color:#999; font-size:0.78rem; line-height:1.6; margin-bottom:12px;">
            Channel Brain isn't just for your audience. Switch to <strong style="color:#d4a359;">Creator Mode</strong>
            and you can search your own archive for:
        </div>
        <ul style="color:#bbb; font-size:0.78rem; line-height:1.7;
                   margin:0; padding-left:18px; list-style: none;">
            <li style="margin-bottom:4px;">
                <span style="color:#d4a359;">→</span>
                <strong style="color:#d4d0c8;">Your best thinking on any topic</strong> for newsletters, talks, or social
            </li>
            <li style="margin-bottom:4px;">
                <span style="color:#d4a359;">→</span>
                <strong style="color:#d4d0c8;">Course and book material</strong> organized by theme, not by episode date
            </li>
            <li>
                <span style="color:#d4a359;">→</span>
                <strong style="color:#d4d0c8;">Content gap analysis</strong> — what your audience wants that you haven't covered yet
            </li>
        </ul>
    </div>

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
            <li>Creator Mode for your own use</li>
            <li>Live in under a week</li>
            <li>Zero work on your end</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Email capture
    if not ss_get("email_submitted"):
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
                success = send_lead_to_webhook(email, channel_name_input, demo_channel=CHANNEL_NAME)
                if success:
                    ss_set("email_submitted", True)
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
                    ss_set("email_submitted", True)
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
        <strong style="color: #888;">{CHANNEL_NAME}</strong> —
        a channel by {CREATOR_NAME}. We indexed it as an example to show creators
        what Channel Brain can do for their own channel.<br><br>
        <strong style="color:#888;">This is not affiliated with or endorsed
        by {CHANNEL_NAME}.</strong><br><br>
        <a href="{CHANNEL_URL}" target="_blank"
           style="color: #d4a359; text-decoration: none;">
            → Visit {CHANNEL_NAME} ↗
        </a>
    </div>
    </div>
    """, unsafe_allow_html=True)
