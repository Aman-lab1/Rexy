"""
REXY MEMORY LOGGER — Phase 5.3
Layer 6: Logs structured interaction data to Supabase after each turn.

What gets stored (per turn):
  - timestamp
  - topic (rough category, not raw message)
  - session length so far (turn count)
  - time-of-day bucket (morning / afternoon / evening / night)

What does NOT get stored:
  - raw message text  (privacy — we log intent, not words)
  - full reply text   (too large, not useful for pattern detection)

Supabase table expected:
  interaction_logs (
    id          uuid primary key default gen_random_uuid(),
    uid         text not null,
    timestamp   timestamptz not null,
    topic       text,
    intent      text,
    time_bucket text,   -- 'morning' | 'afternoon' | 'evening' | 'night'
    turn_count  int,
    created_at  timestamptz default now()
  )
"""

import logging
from datetime import datetime, timezone
from typing import Optional
import supabase_db

logger = logging.getLogger("rexy.memory_logger")

# ─── Time bucket helper ───────────────────────────────────────────────────────

def _time_bucket(hour: int) -> str:
    """Convert hour (0-23) to a human bucket."""
    if 5  <= hour < 12: return "morning"
    if 12 <= hour < 17: return "afternoon"
    if 17 <= hour < 21: return "evening"
    return "night"


# ─── Topic extraction ─────────────────────────────────────────────────────────

# Maps intent → rough topic label stored in logs
# Keeps the log clean — no raw message text
INTENT_TOPIC_MAP = {
    "CHAT":            "general",
    "GREET":           "greeting",
    "WEATHER":         "weather",
    "CALCULATOR":      "math",
    "GET_TIME":        "time",
    "MEMORY":          "memory",
    "WEB_SEARCH":      "web",
    "FILE_READ":       "files",
    "SYSTEM_INFO":     "system",
    "CALENDAR":        "calendar",
    "COMPUTER":        "computer",
    "MUSIC":           "music",
    "EMOTION_SUPPORT": "emotional",
    "ADVISOR":         "boredom",
    "RESET":           "reset",
}

def _topic_from_intent(intent: str) -> str:
    return INTENT_TOPIC_MAP.get(intent, "general")


# ─── Main log function ────────────────────────────────────────────────────────

def log_interaction(
    uid: str,
    intent: str,
    turn_count: int,
) -> None:
    """
    Log one interaction turn to Supabase.
    Called from orchestrator after each successful pipeline run.
    Fire-and-forget — never raises, never blocks the response.

    Args:
        uid:         Firebase user ID
        intent:      Detected intent for this turn
        turn_count:  Current turn number in this session
    """
    try:
        now        = datetime.now(timezone.utc)
        topic      = _topic_from_intent(intent)
        time_slot  = _time_bucket(now.hour)

        record = {
            "uid":         uid,
            "timestamp":   now.isoformat(),
            "topic":       topic,
            "intent":      intent,
            "time_bucket": time_slot,
            "turn_count":  turn_count,
        }

        # Use supabase_db's client directly
        client = supabase_db.get_client()
        if client is None:
            logger.warning("MemoryLogger: Supabase client unavailable, skipping log.")
            return

        client.table("interaction_logs").insert(record).execute()
        logger.debug(f"MemoryLogger: logged turn {turn_count} | {intent} | {time_slot} | uid={uid[:8]}")

    except Exception as e:
        # Never crash the pipeline over a log write
        logger.warning(f"MemoryLogger: failed to log interaction — {e}")