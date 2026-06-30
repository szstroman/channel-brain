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
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Search paths in priority order
CONFIG_SEARCH_PATHS = ["/data/clients.json", "indexes/clients.json"]

# Hardcoded fallback if no config file exists anywhere
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
        }
    }
}

# Cache the validated config across calls — clients.json doesn't change between deploys
_cached_config: Optional[Dict[str, Any]] = None


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


def _validate_and_fill_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes raw parsed JSON and returns a validated, defaults-filled config dict.
    On invalid input, logs warnings and falls back where possible rather than
    crashing — we never want a typo in clients.json to take down the whole demo.
    """
    if not isinstance(raw, dict):
        logger.warning("clients.json root is not a dict — falling back to hardcoded default")
        return HARDCODED_DEFAULT.copy()

    clients = raw.get("clients")
    if not isinstance(clients, dict) or not clients:
        logger.warning("clients.json has no valid 'clients' dict — falling back to hardcoded default")
        return HARDCODED_DEFAULT.copy()

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
        }

    if not validated_clients:
        logger.warning("No valid clients after validation — falling back to hardcoded default")
        return HARDCODED_DEFAULT.copy()

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
    Returns the validated multi-tenant config. Cached after first call.
    Always returns a usable config — never raises and never returns None.
    Pass force_reload=True to bypass cache (useful for tests).
    """
    global _cached_config

    if _cached_config is not None and not force_reload:
        return _cached_config

    config_path = _find_config_file()

    if config_path is None:
        logger.info("No clients.json found in any search path — using hardcoded default")
        _cached_config = HARDCODED_DEFAULT.copy()
        return _cached_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"clients.json is malformed: {e} — falling back to hardcoded default")
        _cached_config = HARDCODED_DEFAULT.copy()
        return _cached_config
    except Exception as e:
        logger.error(f"Unexpected error reading clients.json: {e} — falling back to hardcoded default")
        _cached_config = HARDCODED_DEFAULT.copy()
        return _cached_config

    _cached_config = _validate_and_fill_defaults(raw)
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
        "inactive"  — client found but active=false; UI should show inactive page
        "fallback"  — requested client not found; resolved to default
        "default"   — no client requested; using default
    The first three cases ALWAYS return a usable client_data (the requested,
    or the default if the requested was missing). status tells the caller
    how to handle UI presentation.
    """
    config = load_clients_config()
    default_id = config["default_client"]
    clients = config["clients"]

    sanitized = sanitize_client_id(client_id)

    if sanitized is None:
        return default_id, clients[default_id], "default"

    if sanitized not in clients:
        return default_id, clients[default_id], "fallback"

    client_data = clients[sanitized]
    if not client_data.get("active", True):
        return sanitized, client_data, "inactive"

    return sanitized, client_data, "ok"
