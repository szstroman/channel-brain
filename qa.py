"""
qa.py  -  Answer a question using Pinecone retrieval + Claude generation.
"""

import os
import re
import sqlite3
import threading
from datetime import datetime

import anthropic
import requests
from sentence_transformers import SentenceTransformer


# ── Embedding model (shared with indexer) ─────────────────────────────────────
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


# ── Query counter ──────────────────────────────────────────────────────────────

DB_PATH = os.environ.get("DB_PATH", "query_counts.db")
MONTHLY_QUERY_CAP = int(os.environ.get("MONTHLY_QUERY_CAP", 2000))
CAP_ALERT_THRESHOLD = 0.80


def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_counts
            (client_id TEXT, month TEXT, count INTEGER,
             PRIMARY KEY (client_id, month))
        """)


def get_query_count(client_id: str) -> int:
    """Return this client's query count for the current month."""
    try:
        _init_db()
        month = datetime.now().strftime("%Y-%m")
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT count FROM query_counts WHERE client_id=? AND month=?",
                (client_id, month)
            ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0  # Fail open — don't block queries if DB has issues


def log_query(client_id: str) -> int:
    """Increment count for this client and return new total."""
    try:
        _init_db()
        month = datetime.now().strftime("%Y-%m")
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO query_counts (client_id, month, count) VALUES (?,?,1)
                ON CONFLICT(client_id, month) DO UPDATE SET count = count + 1
            """, (client_id, month))
            row = conn.execute(
                "SELECT count FROM query_counts WHERE client_id=? AND month=?",
                (client_id, month)
            ).fetchone()
        return row[0] if row else 1
    except Exception:
        return 0


def fire_operator_alert(client_id: str, count: int, cap: int, alert_type: str):
    """Fire webhook alert asynchronously — never blocks the user."""
    webhook_url = os.environ.get("ZAPIER_WEBHOOK_URL", "")
    if not webhook_url:
        return

    payload = {
        "type": alert_type,
        "client_id": client_id,
        "count": count,
        "cap": cap,
        "pct": round(count / cap * 100, 1),
        "timestamp": datetime.now().isoformat(),
    }

    def _fire():
        try:
            requests.post(webhook_url, json=payload, timeout=15)
        except Exception:
            pass

    threading.Thread(target=_fire, daemon=True).start()


# ── Main Q&A function ──────────────────────────────────────────────────────────

def _generate_answer_from_context(question: str, matches: list,
                                  system_prompt: str = None) -> tuple[str, list[dict]]:
    """
    Core answer-generation logic used by both live and preloaded paths.
    Takes Pinecone matches and returns (answer_text, sources).
    Does NOT touch the query counter or fire operator alerts — the caller
    is responsible for cap enforcement if applicable.

    Args:
        question: The user's question.
        matches: List of Pinecone match objects (result.matches from query()).
        system_prompt: Override the default system prompt. If None, uses the
            standard audience-mode prompt. Creator Mode passes its own.
    """
    if not matches:
        return "I couldn't find relevant content for that question in this channel's archive.", []

    # ── Build context ──────────────────────────────────────────────────────────
    context_parts = []
    seen_sources = []
    seen_titles_set = set()

    for match in matches:
        # Handle both object-style and dict-style Pinecone responses
        meta = getattr(match, 'metadata', None) or match.get("metadata", {})
        text = meta.get("text", "")
        title = meta.get("title", "Unknown")
        url = meta.get("url", "")
        context_parts.append(f"[From: {title}]\n{text}")
        if title not in seen_titles_set:
            seen_titles_set.add(title)
            seen_sources.append({"title": title, "url": url})

    context = "\n\n---\n\n".join(context_parts)

    # ── Ask Claude ─────────────────────────────────────────────────────────────
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return "Configuration error: Anthropic API key not set.", []

    client = anthropic.Anthropic(api_key=anthropic_key)

    if system_prompt is None:
        system_prompt = DEFAULT_AUDIENCE_SYSTEM_PROMPT

    user_prompt = f"""Based on these transcript excerpts from the YouTube channel:

{context}

---

Question: {question}

Please answer based on the transcripts above."""

    # ── Dynamic max_tokens ─────────────────────────────────────────────────────
    # Scale output budget to question complexity. Reduced from prior 2000/1200/600
    # to 1200/800/500 — typical answers use 700-800 tokens, so the ceiling still
    # has headroom. Cutting the ceiling reduces Claude generation time by ~40%
    # (5-8 seconds saved per synthesis query) without truncating most answers.
    word_count = len(question.split())
    synthesis_keywords = {
        "best", "worst", "most", "overall", "summarize", "summary",
        "compare", "list", "all", "every", "philosophy", "advice",
        "approach", "strategy", "explain", "describe", "breakdown"
    }
    clean_words = set(re.sub(r'[^\w\s]', '', question.lower()).split())
    is_synthesis = bool(clean_words & synthesis_keywords)
    is_compound = question.count("?") > 1 or word_count > 20

    if is_synthesis or is_compound:
        max_tokens = 5000
    elif word_count > 10:
        max_tokens = 2200
    else:
        max_tokens = 1000

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    answer = message.content[0].text
    return answer, seen_sources


def retrieve_matches(question: str, index_wrapper: dict, n_results: int = 8):
    """
    Embed a question and query Pinecone for the top-n matching chunks.
    Returns the raw Pinecone matches list. Shared by live and preloaded paths.
    """
    pinecone_index = index_wrapper["pinecone_index"]
    namespace = index_wrapper["namespace"]

    model = get_model()
    q_embedding = model.encode([question])[0].tolist()

    results = pinecone_index.query(
        vector=q_embedding,
        top_k=n_results,
        namespace=namespace,
        include_metadata=True
    )

    matches = getattr(results, 'matches', None)
    if matches is None:
        matches = results.get("matches", [])
    return matches


DEFAULT_AUDIENCE_SYSTEM_PROMPT = """You are an expert research assistant given transcript excerpts from a YouTube channel.
Answer the user's question based ONLY on the provided transcript excerpts.

Rules:
- Be specific and detailed, citing concrete examples and direct quotes from the transcripts when they strengthen the answer
- If the transcripts genuinely don't address the question, say so directly — but do not add caveats about "browsing more episodes" or "the retrieved sample" when you have substantive content to work with
- Format your answer clearly with bullet points, sections, or numbered lists when helpful
- Reference specific episode titles in the body of the answer when relevant
- Keep answers focused, confident, and actionable
- Do not end your response with disclaimers about the limits of the retrieved content
- Write as a knowledgeable assistant who has read the relevant material, not as a search engine apologizing for what it didn't find"""


CREATOR_SYSTEM_PROMPT = """You are a strategic analyst helping a creator explore their own YouTube archive. The person asking questions IS the creator whose transcripts you are reading. You are showing them patterns, themes, and quotable moments from their own content so they can repurpose it, plan future material, or spot gaps.

Voice and framing:
- Speak in second person: "you", "your", "you've said". Never refer to the creator in third person.
- Frame findings as patterns in THEIR thinking, not as objective claims. "Your consistent framing is..." not "The transcripts say...". "You return to this idea in..." not "This idea appears in...".
- When possible, quantify presence: "You've discussed pricing in about 8 episodes" or "This theme comes up across four episodes including..." — this makes the analysis feel data-driven, not fluffy.
- Reference specific episodes by title when illustrating a point.
- For content gap questions, reason about what's ADJACENT to what's covered. "You cover X thoroughly but rarely address Y, which pairs naturally with your existing content on Z."
- For quotable-line requests, pull actual verbatim quotes and format them as callouts, prioritizing quotes that are punchy, standalone, and could work as social copy.

Rules:
- Answer ONLY from the provided transcript excerpts. If the transcripts genuinely don't cover something, say so directly, but do not add hedge caveats about "the retrieved sample" or "browsing more episodes."
- Format clearly with headers, bullet points, or numbered lists when it aids scanability.
- Keep answers focused, confident, and actionable — the creator is using this to make decisions about their content strategy.
- Do not end with disclaimers about the limits of the retrieved content.
- Write as a strategic advisor who has read the creator's full archive, not as a search engine apologizing for what it didn't find."""


def answer_question(question: str, index_wrapper: dict,
                    client_id: str = "demo",
                    n_results: int = 8,
                    system_prompt: str = None) -> tuple[str, list[dict]]:
    """
    Live query pipeline:
    1. Check query cap — return CAP_REACHED if exceeded.
    2. Log query and fire alerts at thresholds.
    3. Embed question and retrieve top-n chunks from Pinecone.
    4. Send chunks + question to Claude.
    Returns (answer_text, list_of_source_dicts).
    """

    # ── Cap check ──────────────────────────────────────────────────────────────
    current_count = get_query_count(client_id)

    if current_count >= MONTHLY_QUERY_CAP:
        return "CAP_REACHED", []

    # Log query and fire alerts at thresholds
    new_count = log_query(client_id)
    alert_threshold = int(MONTHLY_QUERY_CAP * CAP_ALERT_THRESHOLD)

    if new_count == alert_threshold:
        fire_operator_alert(client_id, new_count, MONTHLY_QUERY_CAP, "80pct")
    elif new_count >= MONTHLY_QUERY_CAP:
        fire_operator_alert(client_id, new_count, MONTHLY_QUERY_CAP, "cap_hit")

    # Retrieve + generate
    matches = retrieve_matches(question, index_wrapper, n_results)
    return _generate_answer_from_context(question, matches, system_prompt)
