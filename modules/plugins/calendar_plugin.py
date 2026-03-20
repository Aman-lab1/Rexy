"""
REXY CALENDAR PLUGIN v2.0
Handles Google Calendar — add, view, delete, and memory+calendar combined.

v2.0 changes:
  - LLM parsing layer for complex natural language (titles, fuzzy dates)
  - Fixed memory format bug (_handle_both now saves correct dict structure)
  - Simple messages skip LLM entirely (gate already extracted clean args)

Two-tier parsing:
  Simple:  "add exam May 20 2pm"        → gate args used directly, no LLM
  Complex: "add my project review with  → LLM extracts title + date cleanly
            the team next Thursday 3pm"

Author: Aman (EEE @ Ahmedabad University)
"""

import json
import logging
import re
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.plugins.calendar")

# ── Optional dependencies ─────────────────────────────────────
try:
    from google.oauth2.credentials import Credentials      # type: ignore
    from google.auth.transport.requests import Request     # type: ignore
    from googleapiclient.discovery import build            # type: ignore
    import dateparser                                       # type: ignore
    CALENDAR_AVAILABLE = True
except ImportError as e:
    CALENDAR_AVAILABLE = False
    logger.warning(f"Calendar plugin dependencies missing: {e}")


class CalendarPlugin(RexyPlugin):

    # ── RexyPlugin interface ──────────────────────────────────
    @property
    def intent_name(self) -> str:
        return "CALENDAR"

    @property
    def description(self) -> str:
        return "Add, view, and delete Google Calendar events"

    @property
    def risk_level(self) -> str:
        return "low"

    @property
    def intent_examples(self) -> List[str]:
        return [
            "add my exam on May 20",
            "what's on my calendar today",
            "cancel the dentist appointment",
            "schedule team meeting tomorrow at 3pm",
        ]

    def __init__(self):
        self._service = None
        self._tz      = None

    # ── Main execute ─────────────────────────────────────────
    def execute(
        self,
        message: str,
        emotion: str,
        state:   Dict[str, Any],
        args:    Dict[str, Any] = {}
    ) -> Dict[str, Any]:

        if not CALENDAR_AVAILABLE:
            return self._unavailable_response()

        if not self._ensure_service():
            return {
                "reply": (
                    "📅 Google Calendar isn't set up yet.\n"
                    "Run this once to authenticate:\n"
                    "  python scripts/google_auth_setup.py"
                ),
                "emotion": "neutral",
                "state":   "speaking"
            }

        action = args.get("action") or self._detect_action(message)
        logger.info(f"CalendarPlugin | action={action} | args={args}")

        if action == "add":    return self._handle_add(message, args, state)
        if action == "view":   return self._handle_view(message, args)
        if action == "delete": return self._handle_delete(message, args)
        if action == "both":   return self._handle_both(message, args, state)

        return {
            "reply": (
                "📅 Calendar — what would you like to do?\n"
                "• Add:    'add physics exam May 20 2pm'\n"
                "• View:   'what's on my calendar today'\n"
                "• Delete: 'cancel the dentist appointment'"
            ),
            "emotion": "neutral",
            "state":   "speaking"
        }

    # ═══════════════════════════════════════════════════════════
    # LLM PARSING LAYER
    # Only fires for complex messages where regex would struggle.
    # Simple messages (clean gate args) skip this entirely.
    # ═══════════════════════════════════════════════════════════

    def _llm_parse_event(self, message: str) -> Dict:
        """
        Use Groq to extract structured event details from natural language.

        Returns dict with any of: title, date, action
        Returns {} if Groq fails — caller falls back to regex.

        Examples:
          "add my project review with the team next Thursday 3pm"
            → {"title": "Project Review", "date": "next Thursday 3pm", "action": "add"}

          "remember my physics exam is May 20 and add to calendar"
            → {"title": "Physics Exam", "date": "May 20", "action": "both"}
        """
        try:
            import groq_client

            prompt = f"""Extract calendar event details from this message.
Respond ONLY with valid JSON, no markdown, no explanation:
{{
  "title": "clean event name only",
  "date": "date and time as written by user, or null",
  "action": "add or view or delete or both"
}}

Message: "{message}"

Rules:
- title: just the event name, strip filler words like "add", "my", "schedule", "remember"
- date: copy the exact date/time phrase from the message, or null if absent
- action: "both" only if message mentions both remembering/memory AND calendar/schedule
- If the title is unclear, make your best guess from the context
- Never include date words in the title"""

            raw = groq_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )

            if not raw:
                return {}

            # Strip markdown fences if present
            raw = re.sub(r'```(?:json)?', '', raw).strip()
            result = json.loads(raw)

            # Validate — only keep fields that actually have values
            clean = {}
            if result.get("title") and len(str(result["title"])) > 1:
                clean["title"] = str(result["title"]).strip()
            if result.get("date"):
                clean["date"] = str(result["date"]).strip()
            if result.get("action"):
                clean["action"] = str(result["action"]).strip().lower()

            logger.info(f"LLM event parse: {clean}")
            return clean

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"LLM event parse failed: {e}")
            return {}

    def _should_use_llm(self, message: str, args: Dict) -> bool:
        """
        Decide if this message needs LLM parsing.

        Skip LLM when:
        - Gate already gave us a clean title
        - Message is short and simple (≤5 words after stripping trigger)
        - It's a view or delete (no title extraction needed)

        Use LLM when:
        - No title in args
        - Message is long/complex (>6 words)
        - Contains phrases like "with", "for", "about", "regarding"
        """
        # Already have a title — no need
        if args.get("title"):
            return False

        # View and delete don't need title parsing
        action = args.get("action", "add")
        if action == "view":
            return False

        # Count meaningful words
        word_count = len(message.split())
        if word_count <= 5:
            return False

        # Complex phrases that regex handles poorly
        complex_indicators = [
            r'\bwith\b', r'\bfor\b', r'\babout\b', r'\breview\b',
            r'\bregarding\b', r'\bdiscuss\b', r'\bcatch up\b',
            r'\bcheck in\b', r'\bsync\b', r'\bdebrief\b'
        ]
        msg_lower = message.lower()
        if any(re.search(p, msg_lower) for p in complex_indicators):
            return True

        # Long message without a clean date from gate
        if word_count > 6 and not args.get("date"):
            return True

        return False

    # ═══════════════════════════════════════════════════════════
    # ADD EVENT
    # ═══════════════════════════════════════════════════════════
    def _handle_add(self, message: str, args: Dict, state: Dict) -> Dict:
        assert self._service is not None

        # ── LLM parsing for complex messages ──
        if self._should_use_llm(message, args):
            logger.info("CalendarPlugin | using LLM parser")
            llm_result = self._llm_parse_event(message)
            # Merge LLM results — LLM wins on title, gate wins on date if cleaner
            if llm_result.get("title"):
                args = {**args, "title": llm_result["title"]}
            if llm_result.get("date") and not args.get("date"):
                args = {**args, "date": llm_result["date"]}

        details = self._parse_event_details(message, args)
        if details is None:
            return {
                "reply":   "📅 I couldn't figure out the date/time. Try:\n'add physics exam on May 20 at 2pm'",
                "emotion": "neutral",
                "state":   "speaking"
            }

        title    = details["title"]
        start_dt = details["start"]
        end_dt   = details["end"]
        all_day  = details["all_day"]

        if all_day:
            event_body = {
                "summary": title,
                "start":   {"date": start_dt.strftime("%Y-%m-%d")},
                "end":     {"date": end_dt.strftime("%Y-%m-%d")},
            }
        else:
            event_body = {
                "summary": title,
                "start":   {"dateTime": start_dt.isoformat(), "timeZone": self._get_tz_str()},
                "end":     {"dateTime": end_dt.isoformat(),   "timeZone": self._get_tz_str()},
            }

        try:
            created  = self._service.events().insert(calendarId="primary", body=event_body).execute()
            event_id = created.get("id", "")
            logger.info(f"Calendar event created: '{title}' id={event_id}")

            date_str = (
                start_dt.strftime("%B %d, %Y")
                if all_day
                else start_dt.strftime("%B %d, %Y at %I:%M %p")
            )
            return {
                "reply":    f"📅 Added to your calendar:\n{title} — {date_str}",
                "emotion":  "happy",
                "state":    "speaking",
                "event_id": event_id
            }
        except Exception as e:
            logger.error(f"Calendar add failed: {e}")
            return {
                "reply":   f"❌ Couldn't add to calendar: {str(e)[:80]}",
                "emotion": "neutral",
                "state":   "speaking"
            }

    # ═══════════════════════════════════════════════════════════
    # VIEW EVENTS
    # ═══════════════════════════════════════════════════════════
    def _handle_view(self, message: str, args: Dict) -> Dict:
        assert self._service is not None
        from config.calendar_config import MAX_EVENTS_SHOWN

        msg_lower = message.lower()
        now       = datetime.now(tz=self._get_tz())

        if "tomorrow" in msg_lower:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end   = start + timedelta(days=1)
            label = "tomorrow"
        elif "week" in msg_lower:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end   = start + timedelta(days=7)
            label = "this week"
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end   = start + timedelta(days=1)
            label = "today"

        try:
            result = self._service.events().list(
                calendarId   = "primary",
                timeMin      = start.isoformat(),
                timeMax      = end.isoformat(),
                maxResults   = MAX_EVENTS_SHOWN,
                singleEvents = True,
                orderBy      = "startTime"
            ).execute()

            events = result.get("items", [])
            if not events:
                return {
                    "reply":   f"📅 Nothing on your calendar {label}. Enjoy the free time! 😊",
                    "emotion": "happy",
                    "state":   "speaking"
                }

            lines = [f"📅 Your schedule for {label}:"]
            for ev in events:
                ev_title = ev.get("summary", "Untitled")
                start_   = ev["start"].get("dateTime") or ev["start"].get("date")
                try:
                    dt     = datetime.fromisoformat(str(start_).replace("Z", "+00:00"))
                    dt_str = dt.astimezone(self._get_tz()).strftime("%I:%M %p")
                except Exception:
                    dt_str = str(start_)
                lines.append(f"  • {ev_title} — {dt_str}")

            return {"reply": "\n".join(lines), "emotion": "neutral", "state": "speaking"}

        except Exception as e:
            logger.error(f"Calendar view failed: {e}")
            return {
                "reply":   f"❌ Couldn't fetch calendar: {str(e)[:80]}",
                "emotion": "neutral",
                "state":   "speaking"
            }

    # ═══════════════════════════════════════════════════════════
    # DELETE EVENT
    # ═══════════════════════════════════════════════════════════
    def _handle_delete(self, message: str, args: Dict) -> Dict:
        assert self._service is not None

        title_keyword = args.get("title") or self._extract_delete_target(message)
        if not title_keyword:
            return {
                "reply":   "📅 What event should I delete? Try: 'cancel my physics exam'",
                "emotion": "neutral",
                "state":   "speaking"
            }

        now = datetime.now(tz=self._get_tz())
        try:
            result = self._service.events().list(
                calendarId   = "primary",
                timeMin      = now.isoformat(),
                timeMax      = (now + timedelta(days=30)).isoformat(),
                maxResults   = 10,
                singleEvents = True,
                orderBy      = "startTime",
                q            = title_keyword
            ).execute()

            events = result.get("items", [])
            if not events:
                return {
                    "reply":   f"📅 No upcoming events matching '{title_keyword}' found.",
                    "emotion": "neutral",
                    "state":   "speaking"
                }

            event    = events[0]
            event_id = event["id"]
            title    = event.get("summary", "Untitled")

            self._service.events().delete(calendarId="primary", eventId=event_id).execute()
            logger.info(f"Calendar event deleted: '{title}' id={event_id}")

            return {
                "reply":   f"🗑️ Deleted from your calendar: {title}",
                "emotion": "neutral",
                "state":   "speaking"
            }

        except Exception as e:
            logger.error(f"Calendar delete failed: {e}")
            return {
                "reply":   f"❌ Couldn't delete event: {str(e)[:80]}",
                "emotion": "neutral",
                "state":   "speaking"
            }

    # ═══════════════════════════════════════════════════════════
    # MEMORY + CALENDAR (BOTH)
    # ═══════════════════════════════════════════════════════════
    def _handle_both(self, message: str, args: Dict, state: Dict) -> Dict:
        results = []

        # ── LLM parsing for complex "both" messages ──
        if self._should_use_llm(message, args):
            llm_result = self._llm_parse_event(message)
            if llm_result.get("title"):
                args = {**args, "title": llm_result["title"]}
            if llm_result.get("date") and not args.get("date"):
                args = {**args, "date": llm_result["date"]}

        # ── Step 1: Calendar ──
        cal_result = self._handle_add(message, args, state)
        if "❌" not in cal_result["reply"]:
            results.append(cal_result["reply"])
        else:
            results.append(f"📅 Calendar failed: {cal_result['reply']}")

        # ── Step 2: Rexy memory ──
        try:
            import supabase_db
            uid     = state.get("uid")
            content = args.get("content") or message
            topic   = args.get("topic") or args.get("title") or "calendar"

            if uid:
                success = supabase_db.save_single_memory(uid, topic, content)
                if success:
                    results.append(f"🧠 Saved to Rexy memory")
                else:
                    results.append("⚠️ Memory save failed")
            else:
                results.append("⚠️ Memory save skipped (no uid in state)")

        except Exception as e:
            logger.warning(f"Memory save in _handle_both failed: {e}")
            results.append("⚠️ Memory save failed")

        return {"reply": "\n".join(results), "emotion": "happy", "state": "speaking"}

    # ═══════════════════════════════════════════════════════════
    # DATE / EVENT PARSING
    # ═══════════════════════════════════════════════════════════
    def _parse_event_details(self, message: str, args: Dict) -> Optional[Dict]:
        from config.calendar_config import DEFAULT_DURATION_MINUTES

        title    = args.get("title") or self._extract_event_title(message)
        date_str = args.get("date") or args.get("datetime")
        start_dt = None

        parse_settings = {
            "TIMEZONE":                 self._get_tz_str(),
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM":        "future"
        }

        if date_str:
            start_dt = dateparser.parse(date_str, settings=parse_settings)  # type: ignore

        if start_dt is None:
            start_dt = dateparser.parse(message, settings=parse_settings)   # type: ignore

        if start_dt is None:
            return None

        time_words = re.search(
            r'\b(\d{1,2}(:\d{2})?\s*(am|pm)|at\s+\d|noon|midnight)\b',
            message, re.IGNORECASE
        )
        all_day = (start_dt.hour == 0 and start_dt.minute == 0 and not time_words)
        end_dt  = (
            start_dt + timedelta(days=1)
            if all_day
            else start_dt + timedelta(minutes=DEFAULT_DURATION_MINUTES)
        )

        return {
            "title":   title or "Untitled Event",
            "start":   start_dt,
            "end":     end_dt,
            "all_day": all_day
        }

    def _extract_event_title(self, message: str) -> Optional[str]:
        msg = message.lower()
        msg = re.sub(
            r'\b(add|schedule|create|set|put|remind me about|a reminder for|'
            r'reminder for|reminder|an event for|event for|my|the|an|a|'
            r'remember|and|to|also|please)\b',
            ' ', msg
        )
        msg = re.sub(
            r'\b(on|at|for|this|next|coming|today|tomorrow|'
            r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
            r'january|february|march|april|may|june|july|august|'
            r'september|october|november|december|'
            r'\d{1,2}(:\d{2})?\s*(am|pm)?|\d{4}|noon|midnight|'
            r'add\s+to\s+calendar|add\s+to\s+google|google\s+calendar)\b',
            ' ', msg
        )
        title = re.sub(r'\s+', ' ', msg).strip().title()
        return title if len(title) >= 2 else None

    def _extract_delete_target(self, message: str) -> Optional[str]:
        match = re.search(
            r'\b(?:cancel|delete|remove)\s+(?:my\s+|the\s+)?(.+?)(?:\s+on\s+.+)?$',
            message, re.IGNORECASE
        )
        return match.group(1).strip() if match else None

    def _detect_action(self, message: str) -> str:
        msg = message.lower()

        if (re.search(r'\b(both|memory and calendar|calendar and memory)\b', msg) or
            re.search(r'\b(remember|remind)\b.+\b(add|calendar|schedule)\b', msg) or
            re.search(r'\b(add|schedule)\b.+\b(remember|memory|remind)\b', msg)):
            return "both"

        if re.search(r'\b(cancel|delete|remove)\b', msg):
            return "delete"

        if (re.search(r'\b(show|what.?s|view|check|see|list|tell me).+'
                      r'(calendar|schedule|events|today|tomorrow|week)\b', msg) or
            re.search(r'\bwhat do i have\b', msg)):
            return "view"

        return "add"

    # ═══════════════════════════════════════════════════════════
    # GOOGLE API SERVICE
    # ═══════════════════════════════════════════════════════════
    def _ensure_service(self) -> bool:
        from config.calendar_config import TOKEN_FILE, SCOPES

        if self._service is not None:
            return True

        if not os.path.exists(TOKEN_FILE):
            logger.warning("google_token.json not found — run: python scripts/google_auth_setup.py")
            return False

        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)  # type: ignore

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())                                        # type: ignore
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
                logger.info("Google Calendar token refreshed.")

            if not creds.valid:
                logger.warning("Google Calendar credentials invalid.")
                return False

            self._service = build("calendar", "v3", credentials=creds)         # type: ignore
            logger.info("Google Calendar service ready.")
            return True

        except Exception as e:
            logger.error(f"Calendar auth error: {e}")
            return False

    def _get_tz(self) -> ZoneInfo:
        if self._tz is None:
            from config.calendar_config import TIMEZONE
            self._tz = ZoneInfo(TIMEZONE)
        return self._tz

    def _get_tz_str(self) -> str:
        from config.calendar_config import TIMEZONE
        return TIMEZONE

    def _unavailable_response(self) -> Dict:
        return {
            "reply": (
                "📅 Calendar plugin needs a few libraries. Run:\n"
                "pip install google-api-python-client google-auth-oauthlib "
                "google-auth-httplib2 dateparser"
            ),
            "emotion": "neutral",
            "state":   "speaking"
        }