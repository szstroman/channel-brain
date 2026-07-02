"""
sync_runner.py — Weekly delta-sync orchestrator for Channel Brain.

Reads clients.json, iterates active clients, calls delta_sync on each.
Designed to be invoked by Railway cron on a weekly schedule (see R2-03).

Usage:
    python sync_runner.py                    # Sync all active clients
    python sync_runner.py --dry-run          # Check for new videos, don't index
    python sync_runner.py --client X         # Sync only client X (also respects --dry-run)
    python sync_runner.py --client X --dry-run

Exit codes:
    0 — all clients synced (or reported no-new-videos) cleanly
    1 — one or more clients failed (see log output for details)
    2 — invalid arguments or fundamental configuration error

Logs to stdout so Railway captures everything. Each client's outcome is a single
line summary + a per-line detail block. Final summary at the end.
"""

import argparse
import json
import sys
import time
import traceback
from typing import Dict, Any, List

# Local imports — sync_runner is a top-level script, siblings to clients_config
from clients_config import load_clients_config
from indexer import delta_sync


def utc_now() -> str:
    """Return current UTC timestamp for log lines."""
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def log(msg: str) -> None:
    """Print a timestamped log line. Uses stdout so Railway captures it."""
    print(f"[{utc_now()}] {msg}", flush=True)


def sync_one_client(client_id: str, client_data: Dict[str, Any],
                    dry_run: bool) -> Dict[str, Any]:
    """
    Run delta_sync for one client with full error isolation.
    Returns the delta_sync result dict, or a synthetic error dict on catastrophic failure.
    """
    channel_name = client_data.get("channel_name", client_id)
    channel_url = client_data.get("channel_url", "")

    log(f"  → Syncing '{client_id}' ({channel_name})")
    if not channel_url:
        log(f"    ! Skipping: no channel_url in clients.json")
        return {
            "client_id": client_id,
            "status": "error",
            "error": "Missing channel_url in clients.json",
            "synced": 0, "skipped": 0,
            "new_video_titles": [], "skipped_video_ids": [],
        }

    try:
        result = delta_sync(
            client_id=client_id,
            channel_url=channel_url,
            dry_run=dry_run,
        )
    except Exception as e:
        # Should never happen — delta_sync catches its own errors.
        # But if it DOES leak, we don't want the whole runner to die.
        log(f"    ! Unhandled exception in delta_sync: {type(e).__name__}: {e}")
        log(f"    ! Traceback:")
        for line in traceback.format_exc().splitlines():
            log(f"      {line}")
        return {
            "client_id": client_id,
            "status": "error",
            "error": f"Unhandled exception: {type(e).__name__}: {e}",
            "synced": 0, "skipped": 0,
            "new_video_titles": [], "skipped_video_ids": [],
        }

    # Log outcome summary for this client
    status = result.get("status", "unknown")
    if status == "ok":
        prefix = "[dry-run] " if dry_run else ""
        log(f"    ✓ {prefix}synced={result['synced']} skipped={result['skipped']} "
            f"({len(result.get('new_video_titles', []))} new)")
        if result.get("new_video_titles"):
            for title in result["new_video_titles"][:10]:
                log(f"      + {title}")
            if len(result["new_video_titles"]) > 10:
                log(f"      + ... and {len(result['new_video_titles']) - 10} more")
    elif status == "no_new_videos":
        log(f"    · No new videos since last sync")
    elif status == "no_existing_index":
        log(f"    ! No existing index — client needs initial build_index run")
    elif status == "error":
        log(f"    ! ERROR: {result.get('error', 'unknown error')}")
    else:
        log(f"    ? unexpected status '{status}': {result}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weekly delta-sync orchestrator for Channel Brain clients."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Check for new videos without indexing (safe test mode)")
    parser.add_argument("--client", default=None,
                        help="Sync only this client_id (default: all active clients)")
    args = parser.parse_args()

    log("=" * 60)
    log(f"sync_runner starting  (dry_run={args.dry_run})")
    if args.client:
        log(f"scope: single client '{args.client}'")
    else:
        log("scope: all active clients")
    log("=" * 60)

    # Load config
    try:
        config = load_clients_config()
    except Exception as e:
        log(f"! FATAL: could not load clients config: {e}")
        return 2

    all_clients = config.get("clients", {})
    if not all_clients:
        log("! FATAL: no clients defined in clients.json")
        return 2

    # Determine target clients
    if args.client:
        if args.client not in all_clients:
            log(f"! FATAL: client '{args.client}' not found in clients.json")
            log(f"  Available: {sorted(all_clients.keys())}")
            return 2
        targets = {args.client: all_clients[args.client]}
    else:
        targets = all_clients

    # Run sync per client, tracking outcomes
    results: List[Dict[str, Any]] = []
    for cid, cdata in targets.items():
        if not cdata.get("active", True):
            log(f"  · Skipping inactive client: '{cid}'")
            continue
        try:
            result = sync_one_client(cid, cdata, args.dry_run)
        except Exception as e:
            # Even sync_one_client's error handling failed — catch anyway
            log(f"! Catastrophic failure processing '{cid}': {e}")
            result = {
                "client_id": cid,
                "status": "error",
                "error": f"Runner-level exception: {e}",
                "synced": 0, "skipped": 0,
                "new_video_titles": [], "skipped_video_ids": [],
            }
        results.append(result)

    # Summary
    log("=" * 60)
    log("Sync Summary")
    log("-" * 60)

    total_synced = sum(r.get("synced", 0) for r in results)
    total_skipped = sum(r.get("skipped", 0) for r in results)
    successes = sum(1 for r in results if r.get("status") in ("ok", "no_new_videos"))
    errors = sum(1 for r in results if r.get("status") == "error")
    no_index = sum(1 for r in results if r.get("status") == "no_existing_index")

    log(f"  Clients processed:      {len(results)}")
    log(f"  Successful:             {successes}")
    log(f"  Errors:                 {errors}")
    log(f"  Missing index files:    {no_index}")
    log(f"  Videos synced (total):  {total_synced}")
    log(f"  Videos skipped (total): {total_skipped}")

    if errors > 0:
        log("")
        log("  Failed clients:")
        for r in results:
            if r.get("status") == "error":
                log(f"    - {r['client_id']}: {r.get('error', 'unknown')}")

    log("=" * 60)
    log(f"sync_runner finished")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
