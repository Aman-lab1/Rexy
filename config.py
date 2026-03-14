"""
REXY CONFIG v1.0
Single source of truth for all settings.
Reads from .env first, falls back to safe defaults.
Also loads config/capabilities.yaml and config/safety_rules.yaml
"""

import os
import yaml
import logging
from dotenv import load_dotenv

# Load .env into environment variables
load_dotenv()

logger = logging.getLogger("rexy.config")

# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────

from typing import Callable, Any

def _get(key: str, default: Any, cast: Callable = str) -> Any:
    """
    Read a value from environment variables.
    Falls back to default if not found.
    cast converts it to the right type (int, float, str).
    """
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return cast(val)
    except (ValueError, TypeError):
        logger.warning(f"Config: couldn't parse '{key}={val}', using default {default!r}")
        return default


def _load_yaml(path: str) -> dict:
    """Load a YAML file. Returns empty dict if file missing or broken."""
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"Config: YAML file not found: {path}")
        return {}
    except yaml.YAMLError as e:
        logger.warning(f"Config: YAML parse error in {path}: {e}")
        return {}

# ─────────────────────────────────────────────
# SERVER
# ─────────────────────────────────────────────

HOST = _get("HOST", "127.0.0.1")
PORT = _get("PORT", 8000, int)

# ─────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────

OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.2")

# ─────────────────────────────────────────────
# PIPELINE THRESHOLDS
# ─────────────────────────────────────────────

CONFIDENCE_THRESHOLD = _get("CONFIDENCE_THRESHOLD", 0.75, float)
HIGH_RISK_THRESHOLD  = _get("HIGH_RISK_THRESHOLD",  0.90, float)

# ─────────────────────────────────────────────
# MEMORY LIMITS
# ─────────────────────────────────────────────

CHAT_HISTORY_LIMIT    = _get("CHAT_HISTORY_LIMIT",    12, int)
EMOTION_HISTORY_LIMIT = _get("EMOTION_HISTORY_LIMIT",  5, int)

# ─────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────

RATE_LIMIT_PER_MINUTE = _get("RATE_LIMIT_PER_MINUTE", 30, int)

# ─────────────────────────────────────────────
# FIREBASE AUTH
# ─────────────────────────────────────────────

FIREBASE_API_KEY    = _get("FIREBASE_API_KEY",    "")
FIREBASE_PROJECT_ID = _get("FIREBASE_PROJECT_ID", "")
FIREBASE_AUTH_DOMAIN= _get("FIREBASE_AUTH_DOMAIN","")

# ─────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────

SUPABASE_URL      = _get("SUPABASE_URL",      "")
SUPABASE_ANON_KEY = _get("SUPABASE_ANON_KEY", "")

# ─────────────────────────────────────────────
# GROQ
# ─────────────────────────────────────────────

GROQ_API_KEY = _get("GROQ_API_KEY", "")

# ─────────────────────────────────────────────
# YAML CONFIG FILES
# ─────────────────────────────────────────────

_capabilities_raw = _load_yaml("config/capabilities.yaml")
_safety_raw       = _load_yaml("config/safety_rules.yaml")

# All capability definitions from capabilities.yaml
CAPABILITIES: list = _capabilities_raw.get("capabilities", [])

# Allowed actions from safety_rules.yaml
ALLOWED_ACTIONS: list  = _safety_raw.get("allowed_actions", [])
BLOCKED_COMMANDS: list = _safety_raw.get("blocked_commands", [])
PERMISSIONS: dict      = _safety_raw.get("permissions", {})

# ─────────────────────────────────────────────
# STARTUP VALIDATION
# Warns you at launch if critical values are missing.
# Won't crash Rexy — just logs a warning.
# ─────────────────────────────────────────────

def validate() -> None:
    """
    Check that critical config values are set.
    Called once on startup from orchestrator.py.
    """
    warnings = []

    if not OLLAMA_MODEL:
        warnings.append("OLLAMA_MODEL is not set")
    if not FIREBASE_API_KEY:
        warnings.append("FIREBASE_API_KEY is not set (needed for auth later)")
    if not SUPABASE_URL:
        warnings.append("SUPABASE_URL is not set (needed for database later)")
    if not CAPABILITIES:
        warnings.append("capabilities.yaml is empty or missing")

    if warnings:
        for w in warnings:
            logger.warning(f"Config warning: {w}")
    else:
        logger.info("Config: all values loaded successfully.")