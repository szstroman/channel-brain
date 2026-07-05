"""
clients_config.py

Loads and validates the multi-tenant clients configuration. This module is
the SINGLE source of truth for which clients exist, which is the default,
and what each client's metadata is. demo_app.py imports from here and
never reads clients.json directly.

Config file lookup order (first existing wins):
  1. /data/clients.json   (Railway persistent volume)
  2. indexes/clients.json (local dev fallback)

If neither exists, falls back to a hardcoded HARDCODED_DEFAULT which preserves
the single-client (Koerner Office) behavior we had before multi-tenant.

Config schema (clients.json):
  {
    "default_client": "koerner-office",
    "clients": {
      "<client_id>": {
        "channel_name": "Display name shown in UI",
        "channel_handle": "@youtubehandle",
        "channel_url": "https://www.youtube.com/@youtubehandle",
        "namespace": "pinecone-namespace",   # usually same as client_id
        "creator_name": "First Last",          # used in disclaimer copy
        "active": true                          # false = show "no longer active" page
      },
      ...
    }
  }

All fields are required EXCEPT 'creator_name' which defaults to channel_name
if missing. Missing fields cause validation warnings but the loader fills
in safe defaults rather than crashing.
"""

import json
import copy
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Search paths in priority order
CONFIG_SEARCH_PATHS = ["/data/clients.json", "indexes/clients.json"]

# Default suggestion questions. Used when a client's config doesn't include
# per-client audience_suggestions or creator_suggestions. These match the
# existing hardcoded questions in demo_app.py for the Koerner Office demo,
# preserving backward compatibility when clients.json has no suggestions.
DEFAULT_AUDIENCE_SUGGESTIONS = [
    "What are Chris' favorite business ideas of all time?",
    "What does Chris say about starting a business with little money?",
    "What are the most common pieces of advice Chris gives entrepreneurs?",
    "What are Chris' top thoughts on service businesses like pressure washing?",
    "What has Chris said about real estate and RV park investing?",
    "What is Chris' best advice for someone just getting started?",
]

DEFAULT_CREATOR_SUGGESTIONS = [
    "What are my top pieces of advice on starting a business with no money?",
    "What themes come up most often in my episodes?",
    "What have I said about pricing services?",
    "Which episodes best summarize my philosophy on entrepreneurship?",
    "What content gaps could I fill based on what I've covered?",
    "Pull my most quotable one-liners about business.",
]

# Hardcoded fallback if no config file exists anywhere.
# Suggestion lists are populated from DEFAULT_*_SUGGESTIONS after they're
# defined below — see the module-level init at the end of this block.
#
# IMPORTANT: When code paths return this fallback, they MUST use copy.deepcopy()
# rather than .copy(). Shallow copies share nested list references, which means
# a caller mutating the returned config's suggestion lists would permanently
# corrupt HARDCODED_DEFAULT for the rest of the process.
HARDCODED_DEFAULT = {
    "default_client": "koerner-office",
    "clients": {
        "koerner-office": {
            "channel_name": "The Koerner Office",
            "channel_handle": "@thekoerneroffice",
            "channel_url": "https://www.youtube.com/@thekoerneroffice",
            "namespace": "koerner-office",
            "creator_name": "Chris Koerner",
            "active": True,
            # Suggestion arrays attached below
        }
    }
}

# Attach default suggestions to HARDCODED_DEFAULT now that both are defined.
# We use list() to make copies so that mutation of the hardcoded default's
# lists doesn't affect the module-level DEFAULT_*_SUGGESTIONS constants.
HARDCODED_DEFAULT["clients"]["koerner-office"]["audience_suggestions"] = list(DEFAULT_AUDIENCE_SUGGESTIONS)
HARDCODED_DEFAULT["clients"]["koerner-office"]["creator_suggestions"] = list(DEFAULT_CREATOR_SUGGESTIONS)

# Cache the validated config across calls. We invalidate the cache when the
# on-disk file's modification time changes, so operator edits to clients.json
# take effect on the next request without needing a service restart.
_cached_config: Optional[Dict[str, Any]] = None
_cached_config_mtime: Optional[float] = None
_cached_config_path: Optional[str] = None


def _find_config_file() -> Optional[Path]:
    """Returns the path to the first existing clients.json, or None."""
    for path_str in CONFIG_SEARCH_PATHS:
        p = Path(path_str)
        if p.exists() and p.is_file():
            return p
    return None


def _coerce_active(value: Any) -> bool:
    """
    Safely coerce a value to a bool for the 'active' field.
    Defends against the JSON-quoted-bool footgun:
      Python's bool("false") is True (any non-empty string is truthy)
      so if an operator writes '"active": "false"' instead of '"active": false'
      the client would silently stay active forever.
    Treats common falsy strings ("false", "no", "0", "off", "") as False.
    Treats common truthy strings ("true", "yes", "1", "on") as True.
    Anything else falls back to Python's default truthiness check.
    Defaults to True (safer to err on the side of "client is live").
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("false", "no", "0", "off", "", "null", "none"):
            return False
        if normalized in ("true", "yes", "1", "on"):
            return True
        # Unrecognized string — default to True but log
        logger.warning(f"Unrecognized 'active' value: {value!r}, defaulting to True")
        return True
    # Unknown type — default to True
    return True


def _coerce_suggestions(value: Any, defaults: list, client_id: str, field_name: str) -> list:
    """
    Safely coerce a suggestions field to a list of non-empty strings.
    Missing/None → use defaults. Non-list → warn + use defaults.
    List with mixed types → keep string entries, drop the rest, use defaults if empty.
    Always returns a NEW list (never a shared reference to defaults).
    """
    if value is None:
        return list(defaults)
    if not isinstance(value, list):
        logger.warning(
            f"Client '{client_id}' has '{field_name}' that is not a list "
            f"(got {type(value).__name__}) — using defaults"
        )
        return list(defaults)

    # Filter to non-empty strings only, trimmed
    cleaned = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            logger.warning(
                f"Client '{client_id}' '{field_name}' entry #{i} is not a string "
                f"(got {type(item).__name__}) — skipping"
            )
            continue
        trimmed = item.strip()
        if not trimmed:
            logger.warning(f"Client '{client_id}' '{field_name}' entry #{i} is empty — skipping")
            continue
        cleaned.append(trimmed)

    if not cleaned:
        logger.warning(
            f"Client '{client_id}' '{field_name}' has no valid entries — using defaults"
        )
        return list(defaults)

    return cleaned


def _validate_and_fill_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes raw parsed JSON and returns a validated, defaults-filled config dict.
    On invalid input, logs warnings and falls back where possible rather than
    crashing — we never want a typo in clients.json to take down the whole demo.
    """
    if not isinstance(raw, dict):
        logger.warning("clients.json root is not a dict — falling back to hardcoded default")
        return copy.deepcopy(HARDCODED_DEFAULT)

    clients = raw.get("clients")
    if not isinstance(clients, dict) or not clients:
        logger.warning("clients.json has no valid 'clients' dict — falling back to hardcoded default")
        return copy.deepcopy(HARDCODED_DEFAULT)

    # Validate each client entry and fill missing fields with safe defaults
    validated_clients: Dict[str, Dict[str, Any]] = {}
    seen_namespaces: Dict[str, str] = {}  # namespace -> client_id, to detect duplicates

    for client_id, cdata in clients.items():
        if not isinstance(cdata, dict):
            logger.warning(f"Client '{client_id}' is not a dict — skipping")
            continue

        # Sanitize client_id: alphanumeric + hyphen only, lowercase
        if not re.match(r"^[a-z0-9-]+$", client_id):
            logger.warning(f"Client id '{client_id}' has invalid characters — skipping")
            continue

        channel_name = cdata.get("channel_name", client_id)
        channel_handle = cdata.get("channel_handle", "")
        channel_url = cdata.get("channel_url", "")
        namespace = cdata.get("namespace", client_id)
        creator_name = cdata.get("creator_name", channel_name)
        active = _coerce_active(cdata.get("active", True))

        # Defensive: any None value should fall back to the default rather than become "None" string
        if channel_name is None:
            channel_name = client_id
        if namespace is None:
            namespace = client_id
        if creator_name is None:
            creator_name = channel_name
        if channel_handle is None:
            channel_handle = ""
        if channel_url is None:
            channel_url = ""

        # Validate suggestion fields. Missing/malformed → use defaults.
        # Present but valid → keep string entries, drop anything else.
        audience_suggestions = _coerce_suggestions(
            cdata.get("audience_suggestions"),
            DEFAULT_AUDIENCE_SUGGESTIONS,
            client_id,
            "audience_suggestions",
        )
        creator_suggestions = _coerce_suggestions(
            cdata.get("creator_suggestions"),
            DEFAULT_CREATOR_SUGGESTIONS,
            client_id,
            "creator_suggestions",
        )

        # Check namespace uniqueness — duplicate namespaces would cause cross-tenant data leaks
        if namespace in seen_namespaces:
            logger.warning(
                f"Client '{client_id}' has duplicate namespace '{namespace}' "
                f"(already used by '{seen_namespaces[namespace]}') — skipping"
            )
            continue
        seen_namespaces[namespace] = client_id

        validated_clients[client_id] = {
            "channel_name": str(channel_name),
            "channel_handle": str(channel_handle),
            "channel_url": str(channel_url),
            "namespace": str(namespace),
            "creator_name": str(creator_name),
            "active": active,
            "audience_suggestions": audience_suggestions,
            "creator_suggestions": creator_suggestions,
        }

    if not validated_clients:
        logger.warning("No valid clients after validation — falling back to hardcoded default")
        return copy.deepcopy(HARDCODED_DEFAULT)

    # Validate default_client — must be a key in validated_clients
    default_client = raw.get("default_client")
    if default_client not in validated_clients:
        # Pick first active client as fallback, or first client if none active
        active_clients = [cid for cid, c in validated_clients.items() if c["active"]]
        if active_clients:
            new_default = active_clients[0]
        else:
            new_default = next(iter(validated_clients.keys()))
        if default_client is not None:
            logger.warning(
                f"default_client '{default_client}' not found in clients dict — "
                f"using '{new_default}' instead"
            )
        default_client = new_default

    return {
        "default_client": default_client,
        "clients": validated_clients,
    }


def load_clients_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    Returns the validated multi-tenant config. Cached after first call, but
    the cache auto-invalidates when clients.json's modification time changes,
    so operator edits take effect on the next request without a restart.
    Always returns a usable config — never raises and never returns None.
    Pass force_reload=True to bypass cache (useful for tests).
    """
    global _cached_config, _cached_config_mtime, _cached_config_path

    config_path = _find_config_file()

    # Auto-invalidate cache if the file changed on disk
    if _cached_config is not None and not force_reload:
        try:
            current_path_str = str(config_path) if config_path else None
            if current_path_str != _cached_config_path:
                # File location changed (e.g. /data path became available)
                force_reload = True
            elif config_path is not None:
                current_mtime = config_path.stat().st_mtime
                if _cached_config_mtime is None or current_mtime != _cached_config_mtime:
                    force_reload = True
        except Exception:
            # If we can't stat the file for any reason, keep using the cache
            # rather than dropping to hardcoded defaults unnecessarily
            pass

    if _cached_config is not None and not force_reload:
        return _cached_config

    if config_path is None:
        logger.info("No clients.json found in any search path — using hardcoded default")
        _cached_config = copy.deepcopy(HARDCODED_DEFAULT)
        _cached_config_mtime = None
        _cached_config_path = None
        return _cached_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Capture mtime AFTER successful read so we don't cache mtime for a
        # file we failed to parse
        current_mtime = config_path.stat().st_mtime
    except json.JSONDecodeError as e:
        logger.error(f"clients.json is malformed: {e} — falling back to hardcoded default")
        _cached_config = copy.deepcopy(HARDCODED_DEFAULT)
        _cached_config_mtime = None
        _cached_config_path = None
        return _cached_config
    except Exception as e:
        logger.error(f"Unexpected error reading clients.json: {e} — falling back to hardcoded default")
        _cached_config = copy.deepcopy(HARDCODED_DEFAULT)
        _cached_config_mtime = None
        _cached_config_path = None
        return _cached_config

    _cached_config = _validate_and_fill_defaults(raw)
    _cached_config_mtime = current_mtime
    _cached_config_path = str(config_path)
    logger.info(
        f"Loaded clients config from {config_path}: "
        f"{len(_cached_config['clients'])} clients, default='{_cached_config['default_client']}'"
    )
    return _cached_config


def sanitize_client_id(raw_input: Optional[str]) -> Optional[str]:
    """
    Cleans a client_id from an untrusted source (URL parameter, etc).
    Returns lowercase alphanumeric+hyphen string, or None if input was invalid.
    Used to defend against weird URL inputs like '?client=KOERNER-OFFICE'
    or '?client=../etc/passwd'.
    """
    if raw_input is None:
        return None
    s = str(raw_input).strip().lower()
    if not s:
        return None
    # Allow only lowercase letters, digits, hyphens (and underscores just in case)
    if not re.match(r"^[a-z0-9_-]+$", s):
        return None
    return s


def get_client(client_id: Optional[str]) -> Tuple[str, Dict[str, Any], str]:
    """
    Resolves a (possibly-untrusted, possibly-None) client_id to a real client.
    Returns: (resolved_client_id, client_data, status)
      status is one of:
        "ok"        — client found and active
        "inactive"  — client (requested OR default) exists but active=false;
                      UI should show inactive page rather than loading the index.
                      Applies whether the visitor asked for a specific client or
                      no client — if the resolved client is inactive, we say so.
        "fallback"  — requested client not found; resolved to default (which IS active)
        "default"   — no client requested; using default (which IS active)
    The status ALWAYS reflects the actual state of the returned client, so the
    caller can trust that status="ok"/"default"/"fallback" implies active=True.
    """
    config = load_clients_config()
    default_id = config["default_client"]
    clients = config["clients"]

    sanitized = sanitize_client_id(client_id)

    # Determine which client we're actually returning
    if sanitized is None:
        # No explicit request — use default
        resolved_id = default_id
        base_status = "default"
    elif sanitized not in clients:
        # Unknown request — fall back to default
        resolved_id = default_id
        base_status = "fallback"
    else:
        resolved_id = sanitized
        base_status = "ok"

    client_data = clients[resolved_id]

    # If the resolved client is inactive, status is always "inactive"
    # (regardless of whether the request was explicit, fallback, or default)
    if not client_data.get("active", True):
        return resolved_id, client_data, "inactive"

    return resolved_id, client_data, base_status
