"""
REXY INPUT ROUTER
Normalizes all input sources into a standard schema.

Schema:
{
    "type":       "chat" | "intent",
    "intent":     str | None,
    "message":    str | None,
    "source":     "keyboard" | "gesture" | "voice" | "system",
    "confidence": float | None,
    "uid":        str,
    "timestamp":  float
}

Rules:
- "chat"   type → must have "message"
- "intent" type → must have "intent"
- gesture  inputs → always "intent" type
- keyboard inputs → always "chat" type
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("rexy.input_router")

# ─── Gesture → Intent mapping ─────────────────────────────────────────────────
GESTURE_MAP: Dict[str, str] = {
    "wave":        "WAKE",
    "open_palm":   "WAKE",
    "swipe_left":  "NAVIGATE_LEFT",
    "swipe_right": "NAVIGATE_RIGHT",
    "fist":        "SELECT",
    "hold":        "SELECT",
}


# ─── Adapters ─────────────────────────────────────────────────────────────────

class KeyboardAdapter:
    """Converts WebSocket text message → standard chat input."""

    @staticmethod
    def normalize(raw: Dict[str, Any], uid: str) -> Optional[Dict[str, Any]]:
        message = raw.get("message", "").strip()
        if not message:
            return None
        return {
            "type":       "chat",
            "intent":     None,
            "message":    message,
            "source":     "keyboard",
            "confidence": 1.0,
            "uid":        uid,
            "timestamp":  time.time(),
        }


class GestureAdapter:
    """
    Converts gesture labels → standard intent input.
    Simulated only — no camera detection yet.
    """

    @staticmethod
    def normalize(gesture: str, uid: str, confidence: float = 1.0) -> Optional[Dict[str, Any]]:
        gesture = gesture.lower().strip()
        intent  = GESTURE_MAP.get(gesture)

        if not intent:
            logger.warning(f"InputRouter: unknown gesture '{gesture}' — ignored")
            return None

        return {
            "type":       "intent",
            "intent":     intent,
            "message":    None,
            "source":     "gesture",
            "confidence": confidence,
            "uid":        uid,
            "timestamp":  time.time(),
        }


# ─── Main normalizer ──────────────────────────────────────────────────────────

def normalize_input(raw: Dict[str, Any], uid: str) -> Optional[Dict[str, Any]]:
    """
    Route raw input to the correct adapter based on source.
    Returns normalized input dict or None if invalid.
    """
    source = raw.get("source", "keyboard")

    if source == "gesture":
        gesture    = raw.get("gesture", "")
        confidence = float(raw.get("confidence", 1.0))
        result     = GestureAdapter.normalize(gesture, uid, confidence)

    else:
        # Default: keyboard
        result = KeyboardAdapter.normalize(raw, uid)

    if result:
        logger.info(
            f"InputRouter | source={result['source']} "
            f"type={result['type']} "
            f"{'message=' + result['message'][:40] if result['message'] else 'intent=' + str(result['intent'])} "
            f"confidence={result['confidence']}"
        )

    return result