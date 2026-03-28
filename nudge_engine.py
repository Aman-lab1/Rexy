"""
REXY NUDGE ENGINE — Phase 5.4
Evaluates user signals and fires one proactive nudge per cycle.

Priority: behavior (1) > task (2) > time (3) > emotional (4)
Frequency: max 5/day, min 90min gap
Suppressed if session was active within last 5 minutes.
"""

import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import supabase_db
import pattern_detector

logger = logging.getLogger("rexy.nudge_engine")

MAX_NUDGES_PER_DAY = 5
MIN_GAP_MINUTES    = 90
INACTIVITY_HOURS   = 6


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _current_bucket() -> str:
    hour = datetime.now().hour
    if 5  <= hour < 12: return "morning"
    if 12 <= hour < 17: return "afternoon"
    if 17 <= hour < 21: return "evening"
    return "night"


def _can_nudge(uid: str) -> bool:
    """Returns True if frequency limits allow a nudge right now."""
    try:
        log = supabase_db.get_nudge_log(uid)
        now   = datetime.now(timezone.utc)
        today = now.date()

        today_nudges = [
            n for n in log
            if datetime.fromisoformat(n["created_at"]).date() == today
        ]

        if len(today_nudges) >= MAX_NUDGES_PER_DAY:
            logger.debug("Nudge suppressed — daily limit reached")
            return False

        if today_nudges:
            last_ts = max(datetime.fromisoformat(n["created_at"]) for n in today_nudges)
            if (now - last_ts) < timedelta(minutes=MIN_GAP_MINUTES):
                logger.debug("Nudge suppressed — too soon after last nudge")
                return False

        return True
    except Exception as e:
        logger.warning(f"Nudge frequency check failed: {e}")
        return False


# ─── Triggers ─────────────────────────────────────────────────────────────────

def _behavior_nudge(patterns: Dict, uid: str) -> Optional[Dict]:
    """Fires if user deviates from their typical pattern."""
    active_time = patterns.get("active_time", "unknown")
    current     = _current_bucket()

    # Late start — morning person, but it's already afternoon
    if active_time == "morning" and current == "afternoon":
        return {
            "nudge_text": "Starting a bit later today?",
            "nudge_type": "behavior",
            "priority":   1
        }

    # Missed yesterday — no logs from yesterday at all
    try:
        client = supabase_db.get_client()
        if client:
            yesterday_start = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            resp = (
                client.table("interaction_logs")
                .select("timestamp")
                .eq("uid", uid)
                .gte("timestamp", yesterday_start)
                .lt("timestamp", today_start)
                .limit(1)
                .execute()
            )
            if not (resp.data or []):
                return {
                    "nudge_text": "Didn't see you yesterday.",
                    "nudge_type": "behavior",
                    "priority":   1
                }
    except Exception:
        pass

    return None


def _time_nudge(patterns: Dict) -> Optional[Dict]:
    """Fires when current time matches user's typical active window."""
    active_time = patterns.get("active_time", "unknown")
    current     = _current_bucket()

    TEXTS = {
        "morning":   ["You usually start around now.", "Seems like your usual time."],
        "afternoon": ["Around your usual afternoon window.", "Your usual time, maybe."],
        "evening":   ["Usually active around now.", "Thinking of jumping in?"],
        "night":     ["Night owl hours.", "Usually up around now."],
    }

    if active_time == current and active_time in TEXTS:
        return {
            "nudge_text": random.choice(TEXTS[active_time]),
            "nudge_type": "time",
            "priority":   3
        }
    return None


def _emotional_nudge(uid: str) -> Optional[Dict]:
    """Fires after long inactivity (> 6 hours)."""
    try:
        client = supabase_db.get_client()
        if not client:
            return None
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=INACTIVITY_HOURS)).isoformat()
        resp = (
            client.table("interaction_logs")
            .select("timestamp")
            .eq("uid", uid)
            .gte("timestamp", cutoff)
            .limit(1)
            .execute()
        )
        if not (resp.data or []):
            return {
                "nudge_text": random.choice(["You've been quiet today.", "Long day?", "Still around?"]),
                "nudge_type": "emotional",
                "priority":   4
            }
    except Exception:
        pass
    return None


# ─── Main entry ───────────────────────────────────────────────────────────────

def evaluate(uid: str, session_active: bool = False) -> Optional[Dict[str, Any]]:
    """
    Evaluate all triggers. Returns highest-priority nudge dict, or None.

    Args:
        uid:            Firebase user ID
        session_active: True if user messaged within last 5 min — suppresses nudges
    """
    if session_active:
        logger.debug("Nudge suppressed — session active")
        return None

    if not _can_nudge(uid):
        return None

    patterns = pattern_detector.get_patterns(uid)
    if not patterns:
        logger.debug("Nudge suppressed — no patterns yet")
        return None

    candidates = []
    for fn in [
        lambda: _behavior_nudge(patterns, uid),
        lambda: _time_nudge(patterns),
        lambda: _emotional_nudge(uid),
    ]:
        result = fn()
        if result:
            candidates.append(result)

    if not candidates:
        return None

    best = min(candidates, key=lambda n: n["priority"])
    best["timestamp"] = datetime.now(timezone.utc).isoformat()

    supabase_db.log_nudge(uid, best["nudge_type"], best["nudge_text"])
    logger.info(f"Nudge fired — uid={uid[:8]} type={best['nudge_type']} text='{best['nudge_text']}'")
    return best