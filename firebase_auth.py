"""
REXY FIREBASE AUTH
Handles Firebase Admin SDK initialization and token verification.
Used by orchestrator.py to verify users on WebSocket connection.
"""

import logging
import firebase_admin
from firebase_admin import credentials, auth

from config import FIREBASE_PROJECT_ID

logger = logging.getLogger("rexy.firebase")

# ─────────────────────────────────────────────
# INITIALIZE FIREBASE ADMIN SDK
# Runs once on startup. Uses firebase_credentials.json.
# ─────────────────────────────────────────────

_initialized = False

def initialize() -> None:
    """
    Initialize Firebase Admin SDK.
    Called once from orchestrator.py on startup.
    Safe to call multiple times — skips if already initialized.
    """
    global _initialized

    if _initialized:
        return

    try:
        cred = credentials.Certificate("firebase_credentials.json")
        firebase_admin.initialize_app(cred)
        _initialized = True
        logger.info(f"Firebase initialized — project: {FIREBASE_PROJECT_ID}")

    except FileNotFoundError:
        logger.error(
            "firebase_credentials.json not found. "
            "Download it from Firebase Console → Project Settings → Service Accounts."
        )
    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")


# ─────────────────────────────────────────────
# VERIFY TOKEN
# Called for every WebSocket connection.
# ─────────────────────────────────────────────

def verify_token(id_token: str) -> dict | None:
    """
    Verify a Firebase ID token sent by the frontend.
    Returns decoded token dict if valid, None if invalid.

    Decoded token contains:
        uid   → unique user ID (use this as the user identifier)
        email → user's email address
        name  → display name (if set)
    """
    if not _initialized:
        logger.warning("Firebase not initialized — skipping token verification.")
        return None

    if not id_token or not id_token.strip():
        logger.warning("Empty token received.")
        return None

    try:
        decoded = auth.verify_id_token(id_token)
        logger.info(f"Token verified — uid: {decoded['uid']}")
        return decoded

    except auth.ExpiredIdTokenError:
        logger.warning("Token expired.")
        return None

    except auth.InvalidIdTokenError:
        logger.warning("Invalid token.")
        return None

    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return None


# ─────────────────────────────────────────────
# GET USER INFO
# ─────────────────────────────────────────────

def get_user(uid: str) -> dict | None:
    """
    Fetch user info from Firebase by UID.
    Returns dict with uid, email, display_name or None on failure.
    """
    if not _initialized:
        return None

    try:
        user = auth.get_user(uid)
        return {
            "uid":          user.uid,
            "email":        user.email,
            "display_name": user.display_name or "Friend"
        }
    except Exception as e:
        logger.warning(f"get_user failed for uid '{uid}': {e}")
        return None