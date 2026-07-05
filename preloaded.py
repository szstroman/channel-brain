"""
preloaded.py — Generate and cache "canned" answers for suggestion questions.

Rationale: the demo shows fixed suggestion questions. If every visitor click
hit Claude live, we'd burn budget on canned demonstrations. Instead we
pre-generate answers weekly (via the sync_runner scheduler) and cache them
per-client. Clicks on suggestions return cached answers instantly at zero
cost. Only free-text write-ins go live.

Cache location: /data/<client_id>_preloaded.json (or indexes/... in local dev)

Cache schema:
  {
    "client_id": "koerner-office",
    "generated_at": "2026-07-06 09:00:00 UTC",
    "audience": {
      "<exact question text>": {
        "answer": "...",
        "sources": [{"title": "...", "url": "..."}, ...]
      }
    },
    "creator": { ... same shape ... }
  }

Lookup is by exact question text. If a suggestion question is edited without
regenerating, we simply miss the cache and fall through to live generation.

CLI usage:
  python preloaded.py --client koerner-office
  python preloaded.py --client koerner-office --mode audience
  python preloaded.py --all  (all active clients)
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Search paths for both READING and WRITING the cache file.
# Reads: first existing file wins.
# Writes: first writable directory wins.
CACHE_SEARCH_DIRS = ["/data", "indexes"]

# Delay between Claude API calls when generating in batch — polite to the API
# and gives us headroom if we ever regenerate for many clients at once.
INTER_QUESTION_DELAY_SEC = 1.0


def _cache_path_for_read(client_id: str) -> Optional[Path]:
    """Find an existing cache file for this client, or None if none exists."""
    for search_dir in CACHE_SEARCH_DIRS:
        candidate = Path(search_dir) / f"{client_id}_preloaded.json"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _cache_path_for_write(client_id: str) -> Optional[Path]:
    """
    Return the path where we should write this client's cache, or None if
    no writable directory exists. Prefers /data (Railway volume) over indexes.

    Directory-existence rules:
      - ABSOLUTE paths (e.g. /data): must already exist. We NEVER auto-create
        absolute directories because that could mask a volume-mount failure
        (e.g. /data unmounted, we'd silently create a phantom /data on the
        ephemeral container fs, and writes disappear when the volume remounts).
      - RELATIVE paths (e.g. indexes): auto-created if missing. Local dev
        convenience — the first run should Just Work.
    """
    for search_dir in CACHE_SEARCH_DIRS:
        d = Path(search_dir)
        # Absolute path: require pre-existence.
        # Relative path: create if missing (local dev convenience).
        if d.is_absolute():
            if not d.exists() or not d.is_dir():
                continue
        else:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
        try:
            # Test writability with a tiny probe file
            probe = d / f".write_probe_{os.getpid()}"
            probe.write_text("ok")
            probe.unlink()
            return d / f"{client_id}_preloaded.json"
        except Exception:
            continue
    return None


def load_cache(client_id: str) -> Optional[Dict[str, Any]]:
    """
    Load the cache for a client. Returns None if no cache exists or if the
    cache is malformed. Never raises — callers should always be able to
    fall back to live generation on cache miss.
    """
    path = _cache_path_for_read(client_id)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Preloaded cache for '{client_id}' is malformed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Could not read preloaded cache for '{client_id}': {e}")
        return None

    # Basic shape check
    if not isinstance(data, dict):
        logger.warning(f"Preloaded cache for '{client_id}' is not a dict")
        return None
    return data


def lookup_preloaded(client_id: str, mode: str, question: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    """
    Look up a preloaded answer for (client_id, mode, question).
    Returns (answer, sources) tuple on hit, None on miss.
    Never raises — misses always fall through to live generation.

    Args:
        client_id: The client namespace.
        mode: "audience" or "creator".
        question: EXACT question text (case-sensitive, trimmed).
    """
    if mode not in ("audience", "creator"):
        logger.warning(f"Unknown preloaded mode: '{mode}'")
        return None

    cache = load_cache(client_id)
    if cache is None:
        return None

    mode_bucket = cache.get(mode)
    if not isinstance(mode_bucket, dict):
        return None

    # Exact-match lookup on trimmed question text
    q_key = question.strip()
    entry = mode_bucket.get(q_key)
    if entry is None:
        return None

    if not isinstance(entry, dict):
        return None
    answer = entry.get("answer")
    sources = entry.get("sources", [])
    if not isinstance(answer, str) or not answer:
        return None
    if not isinstance(sources, list):
        sources = []
    return answer, sources


def _generate_one(question: str, index_wrapper: dict,
                  system_prompt: Optional[str]) -> Tuple[str, List[Dict[str, str]]]:
    """
    Generate a single answer using qa's core pipeline (no counter side effects).
    Isolated so exceptions from one question don't kill the batch.
    """
    # Deferred import — qa.py imports sentence_transformers which is heavy;
    # only load it when actually running generation.
    from qa import retrieve_matches, _generate_answer_from_context

    matches = retrieve_matches(question, index_wrapper, n_results=8)
    return _generate_answer_from_context(question, matches, system_prompt=system_prompt)


def generate_preloaded_answers(client_id: str,
                               index_wrapper: dict,
                               dry_run: bool = False) -> Dict[str, Any]:
    """
    Generate preloaded answers for one client, for BOTH modes (audience + creator).
    Writes result to /data/<client_id>_preloaded.json.

    Args:
        client_id: Which client to regenerate for.
        index_wrapper: Pre-loaded Pinecone index+namespace wrapper (from indexer.load_index).
        dry_run: If True, don't call Claude and don't write the file — just report what
                 WOULD be generated. Useful for verifying wiring before spending API budget.

    Returns dict with:
        client_id, status ("ok" | "no_client" | "no_writable_path" | "no_suggestions" | "partial" | "error"),
        audience_generated, audience_failed, creator_generated, creator_failed,
        total_generated, total_failed, cache_path (str or None), message.
    """
    from clients_config import get_client

    result = {
        "client_id": client_id,
        "status": "ok",
        "audience_generated": 0,
        "audience_failed": 0,
        "creator_generated": 0,
        "creator_failed": 0,
        "total_generated": 0,
        "total_failed": 0,
        "cache_path": None,
        "message": "",
    }

    # Resolve client + get suggestions
    cid, cdata, status = get_client(client_id)
    if status == "fallback" and cid != client_id:
        # Requested client wasn't found; we fell back to default.
        result["status"] = "no_client"
        result["message"] = f"Client '{client_id}' not found; refusing to preload for a different client."
        return result
    if status == "inactive":
        result["status"] = "no_client"
        result["message"] = f"Client '{client_id}' is inactive; skipping preload."
        return result

    audience_qs = cdata.get("audience_suggestions", []) or []
    creator_qs = cdata.get("creator_suggestions", []) or []

    if not audience_qs and not creator_qs:
        result["status"] = "no_suggestions"
        result["message"] = f"Client '{client_id}' has no suggestions in either mode."
        return result

    # Determine where to write (if not dry-run)
    write_path = None
    if not dry_run:
        write_path = _cache_path_for_write(client_id)
        if write_path is None:
            result["status"] = "no_writable_path"
            result["message"] = "No writable directory found (/data or indexes)."
            return result
        result["cache_path"] = str(write_path)

    # Lazy import for the Creator Mode prompt — added in R3-03; import defensively
    # so this module works even before R3-03 lands.
    creator_prompt = None
    try:
        from qa import CREATOR_SYSTEM_PROMPT as creator_prompt
    except ImportError:
        # Creator prompt not yet added — fall back to default (audience prompt).
        # The generated creator-mode answers won't have the creator voice yet,
        # but they'll still work. R3-03 will add the constant.
        logger.info("CREATOR_SYSTEM_PROMPT not yet defined in qa.py — using default")

    # Prepare the output structure
    output = {
        "client_id": client_id,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "audience": {},
        "creator": {},
    }

    # Generate audience mode
    for q in audience_qs:
        q_key = q.strip()
        if not q_key:
            continue
        if dry_run:
            result["audience_generated"] += 1
            continue
        try:
            answer, sources = _generate_one(q_key, index_wrapper, system_prompt=None)
            output["audience"][q_key] = {"answer": answer, "sources": sources}
            result["audience_generated"] += 1
        except Exception as e:
            result["audience_failed"] += 1
            logger.warning(f"[preloaded] audience Q failed for '{client_id}': {q_key!r}: {e}")
        time.sleep(INTER_QUESTION_DELAY_SEC)

    # Generate creator mode
    for q in creator_qs:
        q_key = q.strip()
        if not q_key:
            continue
        if dry_run:
            result["creator_generated"] += 1
            continue
        try:
            answer, sources = _generate_one(q_key, index_wrapper, system_prompt=creator_prompt)
            output["creator"][q_key] = {"answer": answer, "sources": sources}
            result["creator_generated"] += 1
        except Exception as e:
            result["creator_failed"] += 1
            logger.warning(f"[preloaded] creator Q failed for '{client_id}': {q_key!r}: {e}")
        time.sleep(INTER_QUESTION_DELAY_SEC)

    # Aggregate counters
    result["total_generated"] = result["audience_generated"] + result["creator_generated"]
    result["total_failed"] = result["audience_failed"] + result["creator_failed"]

    if dry_run:
        result["message"] = (
            f"[dry-run] Would generate {result['total_generated']} answers "
            f"({result['audience_generated']} audience + {result['creator_generated']} creator) "
            f"for '{client_id}'."
        )
        return result

    # Merge with existing cache: preserve any old questions whose keys are no
    # longer in the suggestion list (safer than deleting content the operator
    # might still want to look at). New questions overwrite old ones with the
    # same key.
    existing = load_cache(client_id) or {}
    for mode in ("audience", "creator"):
        merged = dict(existing.get(mode, {}) or {})
        merged.update(output[mode])
        output[mode] = merged

    # Write the file
    try:
        # Write to a tempfile-adjacent path then rename for atomicity.
        # Otherwise a crash during write leaves a partial/truncated cache.
        tmp = write_path.with_suffix(write_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        tmp.replace(write_path)
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Failed to write cache file: {e}"
        return result

    # Determine final status
    if result["total_failed"] > 0 and result["total_generated"] == 0:
        result["status"] = "error"
    elif result["total_failed"] > 0:
        result["status"] = "partial"
    else:
        result["status"] = "ok"

    result["message"] = (
        f"Wrote {result['total_generated']} answers "
        f"({result['audience_generated']} audience + {result['creator_generated']} creator) "
        f"to {write_path}. Failed: {result['total_failed']}."
    )
    return result


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _cli_main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate preloaded answers for suggestion questions."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="Client_id to regenerate for.")
    group.add_argument("--all", action="store_true",
                       help="Regenerate for all ACTIVE clients in clients.json.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't call Claude or write files — just report intent.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from clients_config import load_clients_config
    from indexer import load_index

    if args.all:
        cfg = load_clients_config()
        targets = [(cid, cdata) for cid, cdata in cfg["clients"].items()
                   if cdata.get("active", True)]
        if not targets:
            print("No active clients to regenerate.", file=sys.stderr)
            return 2
    else:
        cfg = load_clients_config()
        if args.client not in cfg["clients"]:
            print(f"Client '{args.client}' not found in clients.json.", file=sys.stderr)
            return 2
        targets = [(args.client, cfg["clients"][args.client])]

    overall_failed = 0
    for cid, cdata in targets:
        print(f"→ Regenerating preloaded for '{cid}'...")

        # Load the client's Pinecone index
        # First find their stats file
        stats_file = None
        for search_dir in ["/data", "indexes"]:
            candidate = Path(search_dir) / f"{cid}.json"
            if candidate.exists():
                stats_file = str(candidate)
                break
        if stats_file is None:
            print(f"  ! No stats/index file for '{cid}' — skipping.")
            overall_failed += 1
            continue

        try:
            index_wrapper, _ = load_index(stats_file)
        except Exception as e:
            print(f"  ! Failed to load index for '{cid}': {e}")
            overall_failed += 1
            continue

        try:
            r = generate_preloaded_answers(cid, index_wrapper, dry_run=args.dry_run)
        except Exception as e:
            print(f"  ! Unhandled exception: {e}")
            traceback.print_exc()
            overall_failed += 1
            continue

        print(f"  {r['status']}: {r['message']}")
        if r["status"] in ("error", "no_client", "no_writable_path"):
            overall_failed += 1

    return 0 if overall_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_cli_main())
