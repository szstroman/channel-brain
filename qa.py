"""
qa.py  –  Answer a question using retrieved transcript chunks + Claude.
"""

import os
import anthropic
import chromadb


def answer_question(question: str, collection: chromadb.Collection,
                    n_results: int = 8) -> tuple[str, list[str]]:
    """
    1. Embed the question and retrieve the top-n most relevant transcript chunks.
    2. Send chunks + question to Claude to generate an answer.
    Returns (answer_text, list_of_source_titles).
    """

    # 1. Retrieve relevant chunks
    results = collection.query(
        query_texts=[question],
        n_results=n_results,
        include=["documents", "metadatas"],
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]

    if not docs:
        return "I couldn't find relevant content for that question.", []

    # 2. Build context block
    context_parts = []
    seen_titles = []
    for doc, meta in zip(docs, metas):
        title = meta.get("title", "Unknown")
        url = meta.get("url", "")
        context_parts.append(f"[From: {title}]\n{doc}")
        if title not in seen_titles:
            seen_titles.append(title)

    context = "\n\n---\n\n".join(context_parts)

    # 3. Ask Claude
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system_prompt = """You are an expert research assistant that has been given transcript excerpts 
from a YouTube channel. Answer the user's question based ONLY on the provided transcript excerpts.

Rules:
- Be specific and detailed, citing examples from the transcripts
- If the content doesn't contain enough info, say so honestly
- Format your answer clearly with bullet points or sections when helpful
- Reference specific episode titles when relevant
- Keep answers focused and actionable"""

    user_prompt = f"""Based on these transcript excerpts from the YouTube channel:

{context}

---

Question: {question}

Please answer based on the transcripts above."""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    answer = message.content[0].text
    return answer, seen_titles
