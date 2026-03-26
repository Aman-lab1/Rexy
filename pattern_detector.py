"""
REXY PATTERN DETECTOR — Phase 5.3
Layer 7 + 8: Reads interaction logs and detects user habits.

Detects (V1):
  1. Active time of day  — morning / afternoon / evening / night person
  2. Top topics          — what does this user talk about most
  3. Preferred mode      — short bursts vs long sessions
  4. Session length      — average turn count per session

Results are cached in Supabase under user_data['patterns'] so we
don't re-query logs on every single message. Cache refreshes every
30 minutes per user.

Supabase shape used:
  user_data -> patterns: {
    "active_time":    "night",
    "top_topics":     ["general", "weather", "emotional"],
    "session_style":  "long",   -- 'burst' | 'long'
    "last_analysed":  "2026-03-24T22:00:00Z"
  }
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import supabase_db

logger = logging.getLogger("rexy.pattern_detector")

# How long before we re-run analysis (minutes)
CACHE_TTL_MINUTES = 30

# Minimum log entries needed before we trust the patterns
MIN_LOGS_REQUIRED = 8

# Session burst threshold — if avg turns < this, it's burst style
BURST_THRESHOLD = 5


# ─── Main entry point ─────────────────────────────────────────────────────────

def get_patterns(uid: str) -> Optional[Dict[str, Any]]:
    """
    Return detected patterns for this user.
    Uses cached patterns if fresh enough, otherwise re-analyses.

    Returns None if not enough data yet.
    """
    try:
        # Check cache first
        user_data = supabase_db.get_user_data(uid)
        patterns  = (user_data or {}).get("patterns", {})

        if patterns and _cache_is_fresh(patterns.get("last_analysed")):
            logger.debug(f"PatternDetector: using cached patterns for uid={uid[:8]}")
            return patterns

        # Re-analyse from logs
        return _analyse(uid)

    except Exception as e:
        logger.warning(f"PatternDetector: failed to get patterns — {e}")
        return None


# ─── Analysis ────────────────────────────────────────────────────────────────

def _analyse(uid: str) -> Optional[Dict[str, Any]]:
    """
    Pull logs from Supabase and compute patterns.
    Stores result back into user_data['patterns'].
    """
    try:
        client = supabase_db.get_client()
        if client is None:
            return None

        # Fetch last 200 logs for this user (enough for good signal)
        response = (
            client.table("interaction_logs")
            .select("topic, intent, time_bucket, turn_count, timestamp")
            .eq("uid", uid)
            .order("timestamp", desc=True)
            .limit(200)
            .execute()
        )

        logs: List[Dict] = response.data or []

        if len(logs) < MIN_LOGS_REQUIRED:
            logger.debug(f"PatternDetector: not enough logs ({len(logs)}) for uid={uid[:8]}")
            return None

        patterns = {
            "active_time":   _detect_active_time(logs),
            "top_topics":    _detect_top_topics(logs),
            "session_style": _detect_session_style(logs),
            "log_count":     len(logs),
            "last_analysed": datetime.now(timezone.utc).isoformat(),
        }

        # Cache back to Supabase
        _save_patterns(uid, patterns)
        logger.info(f"PatternDetector: patterns updated for uid={uid[:8]} — {patterns}")
        return patterns

    except Exception as e:
        logger.warning(f"PatternDetector: analysis failed — {e}")
        return None


# ─── Detectors ────────────────────────────────────────────────────────────────

def _detect_active_time(logs: List[Dict]) -> str:
    """Most common time bucket across all logs."""
    counts: Dict[str, int] = {}
    for log in logs:
        bucket = log.get("time_bucket", "")
        if bucket:
            counts[bucket] = counts.get(bucket, 0) + 1
    if not counts:
        return "unknown"
    return max(counts, key=lambda k: counts[k])


def _detect_top_topics(logs: List[Dict]) -> List[str]:
    """Top 3 topics by frequency, excluding low-signal ones."""
    SKIP_TOPICS = {"greeting", "reset", "time"}
    counts: Dict[str, int] = {}
    for log in logs:
        topic = log.get("topic", "")
        if topic and topic not in SKIP_TOPICS:
            counts[topic] = counts.get(topic, 0) + 1
    if not counts:
        return []
    sorted_topics = sorted(counts, key=lambda k: counts[k], reverse=True)
    return sorted_topics[:3]


def _detect_session_style(logs: List[Dict]) -> str:
    """
    Burst = short sessions (avg turn_count < threshold).
    Long  = deeper conversations.
    """
    turn_counts = [log.get("turn_count", 1) for log in logs if log.get("turn_count")]
    if not turn_counts:
        return "unknown"
    avg = sum(turn_counts) / len(turn_counts)
    return "burst" if avg < BURST_THRESHOLD else "long"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _cache_is_fresh(last_analysed: Optional[str]) -> bool:
    """True if patterns were analysed within CACHE_TTL_MINUTES."""
    if not last_analysed:
        return False
    try:
        parsed = datetime.fromisoformat(last_analysed)
        age    = datetime.now(timezone.utc) - parsed
        return age < timedelta(minutes=CACHE_TTL_MINUTES)
    except Exception:
        return False


def _save_patterns(uid: str, patterns: Dict[str, Any]) -> None:
    """Write patterns into user_data in Supabase."""
    try:
        existing  = supabase_db.get_user_data(uid) or {}
        memories  = existing.get("memories", {})
        memories["patterns"] = patterns
        supabase_db.save_memories(uid, memories)
    except Exception as e:
        logger.warning(f"PatternDetector: failed to save patterns — {e}")