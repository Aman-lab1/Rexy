"""
REXY MORNING BRIEFING — Desk Buddy V1.2
Assembles a personalized morning snapshot.
Fires once per day on first connect within 5am–1pm window.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import supabase_db
import pattern_detector

logger = logging.getLogger("rexy.morning_briefing")

MORNING_START = 5
CUTOFF_HOUR   = 13


def should_show(uid: str) -> bool:
    hour = datetime.now().hour
    if not (MORNING_START <= hour < CUTOFF_HOUR):
        return False
    return not _shown_today(uid)


def _shown_today(uid: str) -> bool:
    try:
        user_data = supabase_db.get_user_data(uid) or {}
        memories  = user_data.get("memories", {})
        last_date = memories.get("briefing_shown_today", "")
        today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return last_date == today
    except Exception:
        return False


def mark_shown(uid: str) -> None:
    try:
        user_data = supabase_db.get_user_data(uid) or {}
        memories  = user_data.get("memories", {})
        memories["briefing_shown_today"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        supabase_db.save_memories(uid, memories)
    except Exception as e:
        logger.warning(f"Briefing: failed to mark shown — {e}")


def assemble(uid: str, session: Dict) -> Optional[Dict[str, Any]]:
    try:
        weather    = _get_weather(uid)
        calendar   = _get_calendar()
        patterns   = pattern_detector.get_patterns(uid)
        focus      = _build_focus(patterns, calendar)
        reflection = _build_reflection(patterns)

        return {
            "type":        "briefing",
            "weather":     weather,
            "calendar":    calendar,
            "focus":       focus,
            "reflection":  reflection,
            "cutoff_hour": CUTOFF_HOUR,
        }
    except Exception as e:
        logger.error(f"Briefing assembly failed: {e}")
        return None


def _get_weather(uid: str) -> Optional[Dict]:
    try:
        from modules.plugins.weather_plugin import WeatherPlugin
        user_data = supabase_db.get_user_data(uid) or {}
        memories  = user_data.get("memories", {})
        city_entry = memories.get("last_weather_city", {})
        city = city_entry.get("value", "") if isinstance(city_entry, dict) else str(city_entry)
        if not city:
            city = "Ahmedabad"  # ← default fallback
        return WeatherPlugin()._fetch_weather(city)
    except Exception as e:
        logger.warning(f"Briefing weather failed: {e}")
        return None


def _get_calendar() -> Dict:
    try:
        from modules.plugins.calendar_plugin import CalendarPlugin, CALENDAR_AVAILABLE
        if not CALENDAR_AVAILABLE:
            return {"today": [], "overdue": [], "yesterday_count": 0}

        plugin = CalendarPlugin()
        if not plugin._ensure_service():
            return {"today": [], "overdue": [], "yesterday_count": 0}

        tz          = plugin._get_tz()
        now         = datetime.now(tz=tz)
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_today   = start_today + timedelta(days=1)

        def _fmt_time(ev):
            s = ev["start"].get("dateTime") or ev["start"].get("date")
            try:
                dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
                return dt.astimezone(tz).strftime("%H:%M")
            except Exception:
                return ""

        today_raw = plugin._service.events().list(
            calendarId="primary", timeMin=start_today.isoformat(),
            timeMax=end_today.isoformat(), maxResults=6,
            singleEvents=True, orderBy="startTime"
        ).execute().get("items", [])

        yesterday_start = start_today - timedelta(days=1)
        overdue_raw = plugin._service.events().list(
            calendarId="primary", timeMin=yesterday_start.isoformat(),
            timeMax=start_today.isoformat(), maxResults=5,
            singleEvents=True, orderBy="startTime"
        ).execute().get("items", [])

        return {
            "today":           [{"title": e.get("summary","Untitled"), "time": _fmt_time(e)} for e in today_raw],
            "overdue":         [{"title": e.get("summary","Untitled")} for e in overdue_raw],
            "yesterday_count": len(overdue_raw),
        }
    except Exception as e:
        logger.warning(f"Briefing calendar failed: {e}")
        return {"today": [], "overdue": [], "yesterday_count": 0}


def _build_focus(patterns: Optional[Dict], calendar: Dict) -> str:
    overdue_count = len(calendar.get("overdue", []))
    if overdue_count > 0:
        return f"You have {overdue_count} thing{'s' if overdue_count > 1 else ''} carried over — might be worth a look."
    if not patterns:
        return "Mornings seem to work well for your important work."
    active_time   = patterns.get("active_time", "")
    session_style = patterns.get("session_style", "")
    if active_time == "morning":
        return "Mornings seem to work well for your important work."
    if active_time == "night":
        return "You tend to do your best work later — no rush this morning."
    if session_style == "burst":
        return "Short focused sessions seem to work well for you."
    return "Starting early might help today."


def _build_reflection(patterns: Optional[Dict]) -> Optional[str]:
    if not patterns:
        return None
    top_topics    = patterns.get("top_topics", [])
    session_style = patterns.get("session_style", "")
    active_time   = patterns.get("active_time", "")
    TOPIC_LINES = {
        "weather":   "You check the weather quite a bit — planning ahead?",
        "emotional": "You've been going through quite a bit lately.",
        "general":   "You like talking about all sorts of things.",
        "web":       "Always curious about something new.",
        "system":    "You keep a close eye on how things are running.",
        "calendar":  "You're pretty schedule-conscious.",
    }
    if top_topics:
        line = TOPIC_LINES.get(top_topics[0])
        if line:
            return line
    if active_time == "night":
        return "You're a night owl — mornings must feel a bit different."
    if session_style == "long":
        return "You tend to have longer, deeper sessions."
    return None