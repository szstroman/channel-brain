"""
backend/main.py — FastAPI backend for Channel Brain.

Session 2 milestone: ONE endpoint, streaming Claude responses via SSE.
Next.js frontend will call this endpoint. Streamlit demo_app.py is unchanged.

Endpoints:
    POST /api/query/stream    — stream a live Q&A answer as Server-Sent Events
    GET  /health              — trivial health check

Not yet built (coming in later sessions):
    GET  /api/client/{id}     — client config
    POST /api/preloaded       — preloaded cache lookup
    POST /api/lead            — email capture

Run locally:
    cd backend
    pip install -r requirements.txt
    py -m uvicorn main:app --reload --port 8000

Then test with the curl example in backend/README.md.
"""

import os
import sys
import time
import json
import logging
from pathlib import Path
from typing import Optional, AsyncIterator

# Load .env from PARENT directory so backend uses the same env vars as demo_app.py.
# Path resolution is defensive: try parent first, then cwd, then don't complain
# if neither exists (Railway sets env vars via the dashboard, no .env file).
try:
    from dotenv import load_dotenv
    _here = Path(__file__).resolve().parent
    _parent_env = _here.parent / ".env"
    _local_env = _here / ".env"
    if _parent_env.exists():
        load_dotenv(_parent_env)
    elif _local_env.exists():
        load_dotenv(_local_env)
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment

# Make sure we can import qa.py, clients_config.py etc from the parent directory.
# This lets the backend reuse existing project modules without duplication.
_PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import anthropic

# Reuse existing project modules
from qa import retrieve_matches, DEFAULT_AUDIENCE_SYSTEM_PROMPT, CREATOR_SYSTEM_PROMPT
from clients_config import get_client
from indexer import load_index
from preloaded import lookup_preloaded


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── Bootstrap: seed /data volume from repo on every startup ───────────────────
# The committed `bootstrap/` folder is the source of truth. Any *.json there is
# copied into /data/ on startup, overwriting existing files. This way, updating
# a bootstrap file in git and pushing WILL update the deployed cache — no need
# to manually delete files on the Railway volume.
#
# The tradeoff: /data isn't a place to write runtime state anymore (would get
# clobbered on next deploy). For now that's fine — nothing at runtime writes
# to /data. If we later need runtime persistence (e.g., cap counters in a DB),
# we'll move that to a separate location like /data/runtime/.
def _bootstrap_data_volume():
    import shutil
    bootstrap_dir = Path(_PARENT_DIR) / "bootstrap"
    if not bootstrap_dir.exists():
        return

    target_dir = Path("/data")
    try:
        target_dir.mkdir(exist_ok=True)
    except Exception:
        # Can't write to /data (e.g. local dev without /data folder)
        return

    for src in bootstrap_dir.glob("*.json"):
        dest = target_dir / src.name
        try:
            shutil.copy2(src, dest)
            logger.info(f"Bootstrapped {src.name} into /data")
        except Exception as e:
            logger.warning(f"Failed to bootstrap {src.name}: {e}")


_bootstrap_data_volume()


# ── App and CORS ──────────────────────────────────────────────────────────────

app = FastAPI(title="Channel Brain API", version="0.1.0")

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Per-IP rate limits protect against abuse. Two tiers:
#   - Cheap endpoints (health, client config): unlimited
#   - Live query endpoint: burn-the-Anthropic-budget protection
#   - Lead capture: form-spam protection
#
# On Railway, get_remote_address returns Railway's edge proxy IP by default.
# We use X-Forwarded-For (set by Railway's proxy) to get the real client IP.
def _real_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        # X-Forwarded-For can have multiple hops; the first is the original client.
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_real_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# In local dev, Next.js runs on :3000 and backend on :8000. CORS must allow that.
# In production, override CORS_ALLOW_ORIGINS via Railway env var to the actual
# frontend URL(s), e.g. "https://channel-brain-frontend.up.railway.app".
_cors_origins = os.environ.get(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── Request/response schemas ──────────────────────────────────────────────────

class HistoryTurn(BaseModel):
    """One turn in the multi-turn history. `role` is 'user' or 'assistant'."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class QueryStreamRequest(BaseModel):
    """
    Input to the streaming endpoint.

    Fields:
        question:  The current question to answer.
        client_id: Which client's archive to search (e.g., 'koerner-office').
        mode:      'audience' or 'creator' — controls which system prompt is used.
        history:   Prior conversation turns (optional). Empty list = fresh chat.
    """
    question: str = Field(..., min_length=1, max_length=2000)
    client_id: str = Field(..., min_length=1, max_length=100)
    mode: str = Field(default="audience", pattern="^(audience|creator)$")
    history: list[HistoryTurn] = Field(default_factory=list)


# ── Index cache ───────────────────────────────────────────────────────────────
# Loading a Pinecone index takes ~200ms. Cache per client_id so we only pay
# that cost once per process lifetime, not per request.

_INDEX_CACHE: dict[str, dict] = {}


def _get_index_for_client(client_id: str) -> Optional[dict]:
    """Return the Pinecone index wrapper for a client, or None if unavailable."""
    if client_id in _INDEX_CACHE:
        return _INDEX_CACHE[client_id]

    # Find the client's stats JSON file. Same lookup order as demo_app.py.
    stats_file = None
    for search_dir in ["/data", "indexes", "../indexes", "../"]:
        candidate = Path(search_dir) / f"{client_id}.json"
        if candidate.exists() and candidate.is_file():
            stats_file = str(candidate)
            break

    if stats_file is None:
        logger.warning(f"No stats file found for client '{client_id}'")
        return None

    try:
        index_wrapper, _stats = load_index(stats_file)
    except Exception as e:
        logger.error(f"Failed to load index for '{client_id}': {e}")
        return None

    _INDEX_CACHE[client_id] = index_wrapper
    logger.info(f"Loaded and cached index for '{client_id}'")
    return index_wrapper


# ── SSE helpers ───────────────────────────────────────────────────────────────
# Server-Sent Events wire format is very simple:
#   data: <payload>\n\n
# Client (EventSource or fetch/reader) reads chunk-by-chunk.
# We send JSON payloads so the frontend can distinguish token/sources/done/error.

def _sse_event(event_type: str, payload: dict) -> str:
    """Format a single SSE event with a JSON data payload."""
    data = json.dumps({"type": event_type, **payload})
    return f"data: {data}\n\n"


# ── The streaming generator ───────────────────────────────────────────────────

async def _stream_answer(req: QueryStreamRequest) -> AsyncIterator[str]:
    """
    Async generator that:
      1. Loads the client's Pinecone index
      2. Retrieves matching chunks for the question
      3. Emits a 'sources' SSE event so the frontend can render source chips early
      4. Streams tokens from Claude, emitting one 'token' event per delta
      5. Emits a 'done' event at the end (or 'error' on failure)

    Every yielded string is a complete SSE frame ready to send to the wire.
    """
    # ── Resolve client ─────────────────────────────────────────────────────
    try:
        resolved_id, client_data, status = get_client(req.client_id)
    except Exception as e:
        logger.error(f"get_client failed: {e}")
        yield _sse_event("error", {"message": "Client resolution failed"})
        return

    if status == "inactive":
        yield _sse_event("error", {"message": "This client is no longer active"})
        return

    # ── Load index ─────────────────────────────────────────────────────────
    index_wrapper = _get_index_for_client(resolved_id)
    if index_wrapper is None:
        yield _sse_event("error", {"message": "Archive not yet available for this client"})
        return

    # ── Retrieve matching chunks from Pinecone ─────────────────────────────
    # 6 chunks (down from 8) keeps input context lean, which helps multi-turn
    # queries — the full history + retrieved context can otherwise crowd out
    # Claude's output budget and trigger mid-answer truncation.
    try:
        matches = retrieve_matches(req.question, index_wrapper, n_results=6)
    except Exception as e:
        logger.error(f"retrieve_matches failed: {e}")
        yield _sse_event("error", {"message": f"Retrieval failed: {type(e).__name__}"})
        return

    if not matches:
        # No relevant content. Send a graceful "no results" answer as a single token event.
        yield _sse_event("token", {"text": "I couldn't find relevant content for that question in this channel's archive."})
        yield _sse_event("done", {"sources": []})
        return

    # ── Build source list (dedup by title) and emit early ──────────────────
    # Frontend can render source chips as soon as they arrive, before the answer streams.
    seen_titles: set[str] = set()
    sources: list[dict] = []
    context_parts: list[str] = []
    for m in matches:
        meta = getattr(m, "metadata", None) or m.get("metadata", {})
        title = meta.get("title", "Unknown")
        url = meta.get("url", "")
        text = meta.get("text", "")
        context_parts.append(f"[From: {title}]\n{text}")
        if title not in seen_titles:
            seen_titles.add(title)
            sources.append({"title": title, "url": url})

    yield _sse_event("sources", {"sources": sources})

    # ── Assemble the Anthropic messages array ──────────────────────────────
    # Multi-turn: include prior history (capped in the request schema; frontend
    # enforces the 8-turn UX limit). Then append the current question as the
    # final user message, with the RAG context inlined.
    #
    # We inline context in the CURRENT user message rather than in a system
    # prefix because Anthropic's caching/context handling prefers this shape.
    context_str = "\n\n---\n\n".join(context_parts)
    user_prompt = f"""Based on these transcript excerpts from the YouTube channel:

{context_str}

---

Question: {req.question}

Please answer based on the transcripts above."""

    messages: list[dict] = []
    for turn in req.history:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": user_prompt})

    system_prompt = CREATOR_SYSTEM_PROMPT if req.mode == "creator" else DEFAULT_AUDIENCE_SYSTEM_PROMPT

    # Append a conciseness reminder — Claude tends to fill available space,
    # which causes truncation on multi-turn synthesis questions. This nudges
    # tighter structure without losing quality.
    system_prompt = system_prompt + (
        "\n\nAdditional guidance:\n"
        "- Be substantive but concise. Aim for the shortest answer that fully addresses the question.\n"
        "- Use bullet points and short paragraphs. Avoid lengthy prose blocks.\n"
        "- Prefer 3-5 focused points over 8-10 shallow ones.\n"
        "- Cut redundant framing, closing summaries, and 'in conclusion' paragraphs."
    )

    # ── Token allocation ──────────────────────────────────────────────────
    # Same heuristic as qa.py's _generate_answer_from_context. Bump synthesis
    # back to 1500 to avoid mid-sentence truncation on rich queries.
    import re
    word_count = len(req.question.split())
    synthesis_keywords = {
        "best", "worst", "most", "overall", "summarize", "summary",
        "compare", "list", "all", "every", "philosophy", "advice",
        "approach", "strategy", "explain", "describe", "breakdown",
    }
    clean_words = set(re.sub(r"[^\w\s]", "", req.question.lower()).split())
    is_synthesis = bool(clean_words & synthesis_keywords)
    is_compound = req.question.count("?") > 1 or word_count > 20

    if is_synthesis or is_compound:
        max_tokens = 3500
    elif word_count > 10:
        max_tokens = 1800
    else:
        max_tokens = 900

    # ── Stream from Anthropic ─────────────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield _sse_event("error", {"message": "Server misconfigured: ANTHROPIC_API_KEY not set"})
        return

    client = anthropic.Anthropic(api_key=api_key)

    try:
        # The stream() context manager handles connection lifecycle cleanly.
        # `text_stream` yields incremental text chunks (not necessarily single
        # tokens — the SDK batches). Fine for our UI: it feels token-ish.
        with client.messages.stream(
            model="claude-sonnet-4-5",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text_chunk in stream.text_stream:
                if not text_chunk:
                    continue
                yield _sse_event("token", {"text": text_chunk})
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        yield _sse_event("error", {"message": f"AI service error: {type(e).__name__}"})
        return
    except Exception as e:
        logger.error(f"Unexpected streaming error: {e}")
        yield _sse_event("error", {"message": f"Unexpected error: {type(e).__name__}"})
        return

    # ── Done event ─────────────────────────────────────────────────────────
    # Frontend uses this to know streaming is complete (vs a dropped connection).
    yield _sse_event("done", {"sources": sources})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Trivial health check for Railway's load balancer / uptime monitors."""
    return {"status": "ok", "service": "channel-brain-api"}


@app.post("/api/query/stream")
@limiter.limit("15/minute")
async def query_stream(request: Request, req: QueryStreamRequest):
    """
    Stream a Q&A answer for the given question. Uses Server-Sent Events.

    Response body is a sequence of SSE frames:
        data: {"type": "sources", "sources": [{"title": "...", "url": "..."}]}\n\n
        data: {"type": "token", "text": "The"}\n\n
        data: {"type": "token", "text": " answer"}\n\n
        ...
        data: {"type": "done", "sources": [...]}\n\n

    Or on failure:
        data: {"type": "error", "message": "..."}\n\n
    """
    return StreamingResponse(
        _stream_answer(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # X-Accel-Buffering off is a hint for reverse proxies (nginx et al)
            # to not buffer the stream. Railway's proxy respects this.
            "X-Accel-Buffering": "no",
        },
    )


# ── Client config endpoint ────────────────────────────────────────────────────

@app.get("/api/client/{client_id}")
async def get_client_config(client_id: str):
    """
    Return client display data + suggestions for both modes.
    Frontend uses this to render the hero copy and suggestion buttons.
    """
    try:
        resolved_id, client_data, status = get_client(client_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Client resolution failed")

    if status == "inactive":
        raise HTTPException(status_code=410, detail="This client is no longer available")

    return {
        "client_id": resolved_id,
        "status": status,
        "channel_name": client_data.get("channel_name", ""),
        "channel_handle": client_data.get("channel_handle", ""),
        "channel_url": client_data.get("channel_url", ""),
        "creator_name": client_data.get("creator_name", ""),
        "audience_suggestions": client_data.get("audience_suggestions", []),
        "creator_suggestions": client_data.get("creator_suggestions", []),
    }


# ── Preloaded cache lookup ────────────────────────────────────────────────────

class PreloadedRequest(BaseModel):
    """Request body for preloaded lookup."""
    client_id: str = Field(..., min_length=1, max_length=100)
    mode: str = Field(..., pattern="^(audience|creator)$")
    question: str = Field(..., min_length=1, max_length=2000)


@app.post("/api/preloaded")
@limiter.limit("30/minute")
async def preloaded_lookup(request: Request, req: PreloadedRequest):
    """
    Look up a preloaded answer for (client_id, mode, question).
    Returns the cached answer + sources on hit, or 404 on miss.
    Never proxies to Claude — this is the "instant" path for suggestion clicks.
    """
    try:
        cached = lookup_preloaded(req.client_id, req.mode, req.question)
    except Exception:
        # lookup_preloaded is documented to never raise, but be defensive
        raise HTTPException(status_code=404, detail="No cached answer")

    if cached is None:
        raise HTTPException(status_code=404, detail="No cached answer")

    answer, sources = cached
    return {"answer": answer, "sources": sources}


# ── Lead capture ──────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    """Request body for lead capture form."""
    email: str = Field(..., min_length=3, max_length=200)
    channel_url: str = Field(default="", max_length=500)
    client_id: str = Field(default="", max_length=100)
    consent: bool = Field(...)


@app.post("/api/lead")
@limiter.limit("5/minute")
async def submit_lead(request: Request, req: LeadRequest):
    """
    Handle lead capture form submission.
    Validates consent, forwards to Zapier webhook if configured.
    Returns success even if Zapier is unavailable — we log locally and never
    block the user, since they've done their part.
    """
    # Consent is mandatory — legal requirement, not just UX
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent required")

    # Very light email validation — just check it has an @ and a dot
    email = req.email.strip()
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Log every lead locally so we never lose one, even if Zapier fails.
    # In production, replace with database write.
    logger.info(
        f"[lead] email={email!r} channel={req.channel_url!r} "
        f"client={req.client_id!r} consent=True"
    )

    # Resolve the client's display name so Zapier gets a human-readable "which
    # demo did they come from" value instead of the internal client_id slug.
    try:
        _, client_data, _ = get_client(req.client_id)
        demo_channel_name = client_data.get("channel_name") or req.client_id or "Unknown"
    except Exception:
        demo_channel_name = req.client_id or "Unknown"

    # Forward to Zapier if webhook is configured.
    # Payload shape MUST match what the Zapier automation expects — same field
    # names the old Streamlit demo sent, so no automation re-config needed.
    zapier_url = os.environ.get("ZAPIER_WEBHOOK_URL")
    if zapier_url:
        try:
            import requests
            resp = requests.post(
                zapier_url,
                json={
                    "email": email,
                    "channel": req.channel_url.strip() or "Not provided",
                    "source": "Channel Brain Demo",
                    "demo_channel": demo_channel_name,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                },
                timeout=5,
            )
            if resp.status_code >= 400:
                logger.warning(
                    f"[lead] Zapier returned {resp.status_code}: {resp.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"[lead] Zapier post failed: {type(e).__name__}: {e}")
    else:
        logger.info("[lead] no ZAPIER_WEBHOOK_URL set, skipping forwarding")

    return {"status": "ok"}
