"""
REXY CALENDAR CONFIG
Central settings for the Google Calendar plugin.
Edit TIMEZONE to match your location.
"""

import os

# ── Your local timezone ──────────────────────────────────────
# Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
TIMEZONE = "Asia/Kolkata"

# ── File paths ───────────────────────────────────────────────
# google_credentials.json  → downloaded from Google Cloud Console (you did this)
# google_token.json        → auto-created after first auth run, never commit this
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "google_credentials.json")
TOKEN_FILE       = os.path.join(os.path.dirname(os.path.dirname(__file__)), "google_token.json")

# ── Calendar API scope ───────────────────────────────────────
# This scope allows read + write. If you only want read-only,
# change to: https://www.googleapis.com/auth/calendar.readonly
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ── Default event duration (minutes) ────────────────────────
# Used when user doesn't specify an end time.
# "add my exam on May 20" → creates a 60-minute event by default
DEFAULT_DURATION_MINUTES = 60

# ── How many events to show when viewing calendar ────────────
MAX_EVENTS_SHOWN = 5

# ── Default calendar ─────────────────────────────────────────
# "primary" = your main Google Calendar
# To use a different calendar, paste its ID here
CALENDAR_ID = "primary"