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

def answer_question(question: str, index_wrapper: dict,
                    client_id: str = "demo",
                    n_results: int = 8) -> tuple[str, list[str]]:
    """
    1. Check query cap — return CAP_REACHED if exceeded.
    2. Embed question and retrieve top-n chunks from Pinecone.
    3. Send chunks + question to Claude.
    Returns (answer_text, list_of_source_titles).
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

    # ── Retrieve from Pinecone ─────────────────────────────────────────────────
    pinecone_index = index_wrapper["pinecone_index"]
    namespace = index_wrapper["namespace"]

    # Embed the question
    model = get_model()
    q_embedding = model.encode([question])[0].tolist()

    # Query Pinecone
    results = pinecone_index.query(
        vector=q_embedding,
        top_k=n_results,
        namespace=namespace,
        include_metadata=True
    )

    matches = getattr(results, 'matches', None)
    if matches is None:
        matches = results.get("matches", [])

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

    system_prompt = """You are an expert research assistant given transcript excerpts from a YouTube channel.
Answer the user's question based ONLY on the provided transcript excerpts.

Rules:
- Be specific and detailed, citing examples from the transcripts
- If the content doesn't contain enough info, say so honestly
- Format your answer clearly with bullet points or sections when helpful
- Reference specific episode titles when relevant
- Keep answers focused and actionable
- For broad philosophy or synthesis questions, note that your answer reflects
  the retrieved sample of episodes and may not capture the creator's full body
  of work. Suggest browsing the channel for deeper context."""

    user_prompt = f"""Based on these transcript excerpts from the YouTube channel:

{context}

---

Question: {question}

Please answer based on the transcripts above."""

    # ── Dynamic max_tokens ─────────────────────────────────────────────────────
    # Scale output budget to question complexity — no point allocating 2000
    # tokens for a simple factual question that needs 100.
    #
    # Signals of complexity:
    #   - Word count of the question
    #   - Synthesis keywords (best, overall, most, compare, summarize, list all)
    #   - Question mark count (compound questions)
    #
    word_count = len(question.split())
    synthesis_keywords = {
        "best", "worst", "most", "overall", "summarize", "summary",
        "compare", "list", "all", "every", "philosophy", "advice",
        "approach", "strategy", "explain", "describe", "breakdown"
    }
    # Strip punctuation before matching so "best?" correctly matches "best"
    clean_words = set(re.sub(r'[^\w\s]', '', question.lower()).split())
    is_synthesis = bool(clean_words & synthesis_keywords)
    is_compound = question.count("?") > 1 or word_count > 20

    if is_synthesis or is_compound:
        max_tokens = 2000   # Complex / synthesis question — full budget
    elif word_count > 10:
        max_tokens = 1200   # Medium question — moderate budget
    else:
        max_tokens = 600    # Simple / factual question — tight budget

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    answer = message.content[0].text
    return answer, seen_sources
