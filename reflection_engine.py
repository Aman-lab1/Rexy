"""
REXY REFLECTION ENGINE — Phase 5.3
Layer 9: Uses detected patterns to add subtle, human-like observations
to Rexy's replies.

Rules (strict):
  - MAX 1 reflection per session (enforced in Supabase)
  - Only triggers when context genuinely matches the pattern
  - Never forces it — returns None if conditions aren't right
  - Reflections are woven into the reply, not appended robotically

Supabase flag used:
  user_data -> memories -> reflection_used_today: "YYYY-MM-DD"
  If this equals today's date → skip reflection entirely.
"""

import logging
import random
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import groq_client
import supabase_db

logger = logging.getLogger("rexy.reflection")

# ─── Context matchers ─────────────────────────────────────────────────────────
# Only reflect when the current turn's context matches the pattern.
# This prevents Rexy from randomly injecting "you're a night owl"
# at 9am into an unrelated message.

def _context_matches(patterns: Dict[str, Any], intent: str, time_bucket: str) -> Optional[str]:
    """
    Check if current context warrants a reflection.
    Returns a reflection type string if yes, None if not.

    Reflection types: 'active_time' | 'topic' | 'session_style'
    """
    active_time   = patterns.get("active_time", "")
    top_topics    = patterns.get("top_topics", [])
    session_style = patterns.get("session_style", "")

    # ── Active time match ──
    # Only mention late-night usage if it's actually late night right now
    if active_time in ("night", "evening") and time_bucket in ("night", "evening"):
        return "active_time"

    if active_time == "morning" and time_bucket == "morning":
        return "active_time"

    # ── Topic match ──
    # Only reflect on topics when the current message is in that topic
    INTENT_TOPIC = {
        "WEATHER": "weather", "CHAT": "general",
        "EMOTION_SUPPORT": "emotional", "WEB_SEARCH": "web",
        "SYSTEM_INFO": "system", "CALENDAR": "calendar",
    }
    current_topic = INTENT_TOPIC.get(intent, "")
    if current_topic and current_topic in top_topics[:2]:
        # Only reflect on topic if it's genuinely dominant (appears in top 2)
        if top_topics and top_topics[0] == current_topic:
            return "topic"

    # ── Session style match ──
    # Only mention session style on CHAT turns (natural conversation moment)
    if session_style == "long" and intent == "CHAT":
        return "session_style"

    return None


# ─── Main entry point ─────────────────────────────────────────────────────────

def maybe_reflect(
    uid: str,
    reply: str,
    intent: str,
    patterns: Optional[Dict[str, Any]],
) -> str:
    """
    Optionally weave a pattern observation into Rexy's reply.

    Returns the original reply unchanged if:
      - No patterns available
      - Already reflected once today
      - Context doesn't match
      - LLM call fails

    Returns a naturally rewritten reply if a reflection is woven in.
    """
    if not patterns:
        return reply

    try:
        # ── Check daily flag ──
        if _already_reflected_today(uid):
            return reply

        # ── Check context match ──
        now         = datetime.now(timezone.utc)
        time_bucket = _time_bucket(now.hour)
        reflection_type = _context_matches(patterns, intent, time_bucket)

        if reflection_type is None:
            return reply

        # ── Build observation hint ──
        observation = _build_observation(reflection_type, patterns, time_bucket)
        if not observation:
            return reply

        # ── Weave into reply via LLM ──
        woven = _weave(reply, observation)
        if not woven:
            return reply

        # ── Mark as used for today ──
        _mark_reflected(uid)
        logger.info(f"Reflection: woven '{reflection_type}' for uid={uid[:8]}")
        return woven

    except Exception as e:
        logger.warning(f"Reflection: failed — {e}")
        return reply


# ─── Observation builder ──────────────────────────────────────────────────────

def _build_observation(
    reflection_type: str,
    patterns: Dict[str, Any],
    time_bucket: str,
) -> Optional[str]:
    """
    Build a short natural observation hint based on pattern type.
    These are prompts for the LLM weaver, not final text.
    """
    active_time   = patterns.get("active_time", "")
    top_topics    = patterns.get("top_topics", [])
    session_style = patterns.get("session_style", "")

    if reflection_type == "active_time":
        if active_time in ("night", "evening"):
            options = [
                "notice the user tends to be active late",
                "observe they seem to show up often in the evenings",
                "gently note it's another late one for them",
            ]
        else:
            options = [
                "notice the user tends to start their day early",
                "observe they're an early riser",
            ]
        return random.choice(options)

    if reflection_type == "topic":
        if top_topics:
            topic = top_topics[0]
            topic_phrases = {
                "weather":   "notice they check the weather a lot",
                "emotional": "sense they've been going through quite a bit lately",
                "general":   "notice they like to talk about all sorts of things",
                "web":       "notice they're always curious about something new",
                "system":    "notice they keep a close eye on their system",
                "calendar":  "notice they're pretty schedule-conscious",
            }
            phrase = topic_phrases.get(topic)
            return phrase

    if reflection_type == "session_style":
        options = [
            "notice this has been a good long conversation",
            "observe they tend to have deeper, longer chats",
        ]
        return random.choice(options)

    return None


# ─── LLM weaver ───────────────────────────────────────────────────────────────

def _weave(reply: str, observation: str) -> Optional[str]:
    """
    Ask the LLM to naturally weave a subtle observation into the reply.
    The observation should feel like a passing thought, not a statement.
    """
    prompt = f"""You have a reply to give to a user, and a subtle observation about their habits.
Rewrite the reply to naturally include the observation — like a passing thought, not a formal statement.

Rules:
- Keep the original reply's meaning fully intact
- The observation should feel offhand, warm, not analytical
- Maximum 1 sentence added or changed
- Do NOT say things like "I've noticed" or "I observe" — make it feel natural
- Do NOT make it creepy or surveillance-like
- If it doesn't fit naturally, just return the original reply unchanged

Original reply:
"{reply}"

Observation to weave in (subtle, passing):
"{observation}"

Output only the final reply. Nothing else."""

    result = groq_client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=250
    )

    if result and result.strip():
        return result.strip().strip('"').strip("'")
    return None


# ─── Daily flag helpers ───────────────────────────────────────────────────────

def _already_reflected_today(uid: str) -> bool:
    """Check if Rexy already reflected for this user today."""
    try:
        user_data = supabase_db.get_user_data(uid) or {}
        memories  = user_data.get("memories", {})
        last_date = memories.get("reflection_used_today", "")
        today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return last_date == today
    except Exception:
        return False


def _mark_reflected(uid: str) -> None:
    """Mark that Rexy has reflected once today for this user."""
    try:
        user_data = supabase_db.get_user_data(uid) or {}
        memories  = user_data.get("memories", {})
        memories["reflection_used_today"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        supabase_db.save_memories(uid, memories)
    except Exception as e:
        logger.warning(f"Reflection: failed to mark used — {e}")


def _time_bucket(hour: int) -> str:
    if 5  <= hour < 12: return "morning"
    if 12 <= hour < 17: return "afternoon"
    if 17 <= hour < 21: return "evening"
    return "night"