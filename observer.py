# observer.py
"""
REXY OBSERVABILITY v1 - PASSIVE FLIGHT RECORDER
Append-only | Read-only | Zero behavioral impact
"""

import json
import hashlib
import os
from datetime import datetime
from typing import Any, Dict

# Ensure log directory exists
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "rexy_observer.log")

os.makedirs(LOG_DIR, exist_ok=True)

def hash_user_input(text: str) -> str:
    """Hash sensitive user input - never store raw text."""
    if not text:
        return "EMPTY"
    return hashlib.sha256(text.encode()).hexdigest()[:8]

def emit(event_type: str, payload: Dict[str, Any]):
    """
    PASSIVE: One function. Append-only. Fail silently.
    Called AFTER decisions - zero control flow impact.
    """
    try:
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "payload": payload
        }
        
        # Anonymize user input in payload
        if "user_message" in payload:
            payload["user_hash"] = hash_user_input(payload["user_message"])
            del payload["user_message"]
        
        line = json.dumps(log_entry) + "\n"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # NEVER crash Rexy

# DEFINED EVENT TYPES (exact strings required)
EVENT_TYPES = {
    "INTENT_SELECTED",    # After IntentDetector
    "SAFETY_CHECK",       # After SafetyVerifier  
    "DECISION_NOTE",      # REJECT/ALLOW/CLARIFY
    "EXECUTION_RESULT",   # After execute()
    "UNCERTAINTY_FLAG"    # Low confidence/reliability
}
