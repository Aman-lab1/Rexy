"""
REXY SUPABASE DATABASE
Handles per-user persistent storage.
Stores memories and identity separately per user.
Replaces the flat JSON files (memories.json, identity.json)
for multi-user support.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_ANON_KEY

logger = logging.getLogger("rexy.supabase")

def get_client():
    """Return the raw Supabase client for direct table access."""
    return _client  # whatever your internal client variable is named

# ─────────────────────────────────────────────
# CLIENT
# ─────────────────────────────────────────────

_client: Optional[Client] = None

def initialize() -> None:
    """
    Initialize Supabase client.
    Called once on startup from orchestrator.py.
    """
    global _client

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.warning("Supabase credentials missing — skipping initialization.")
        return

    try:
        _client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        logger.info("Supabase initialized successfully.")
    except Exception as e:
        logger.error(f"Supabase initialization failed: {e}")


def _check() -> bool:
    """Returns True if client is ready."""
    if _client is None:
        logger.warning("Supabase not initialized.")
        return False
    return True

# ─────────────────────────────────────────────
# GET USER DATA
# ─────────────────────────────────────────────

def get_user_data(uid: str) -> Optional[Dict]:
    """
    Fetch a user's data from Supabase.
    Returns dict with memories and identity, or None if not found.
    """
    if not _check():
        return None
    assert _client is not None
    try:
        result = _client.table("user_data").select("*").eq("uid", uid).execute()
        if result.data:
            return dict(result.data[0])
        return None
    except Exception as e:
        logger.error(f"get_user_data failed for uid '{uid}': {e}")
        return None

# ─────────────────────────────────────────────
# CREATE USER
# ─────────────────────────────────────────────

def create_user(uid: str, email: str) -> bool:
    """
    Create a new user row in Supabase.
    Called when a user connects for the first time.
    Returns True on success.
    """
    if not _check():
        return False
    assert _client is not None
    try:
        _client.table("user_data").insert({
            "uid":      uid,
            "email":    email,
            "memories": {},
            "identity": {}
        }).execute()
        logger.info(f"New user created in Supabase — uid: {uid} email: {email}")
        return True
    except Exception as e:
        logger.error(f"create_user failed for uid '{uid}': {e}")
        return False

# ─────────────────────────────────────────────
# SAVE MEMORIES (full dict overwrite)
# ─────────────────────────────────────────────

def save_memories(uid: str, memories: Dict) -> bool:
    """
    Save a user's memories to Supabase.
    Overwrites the entire memories field.
    Use save_single_memory() when adding just one entry.
    """
    if not _check():
        return False
    assert _client is not None
    try:
        _client.table("user_data").update({
            "memories": memories
        }).eq("uid", uid).execute()
        logger.debug(f"Memories saved for uid: {uid}")
        return True
    except Exception as e:
        logger.error(f"save_memories failed for uid '{uid}': {e}")
        return False

# ─────────────────────────────────────────────
# SAVE SINGLE MEMORY (safe, enforces format)
# ─────────────────────────────────────────────

def save_single_memory(uid: str, key: str, value: str) -> bool:
    """
    Add or update a single memory entry for a user.

    This is the ONLY correct way for plugins to write to memory.
    Always saves in the format MemoryPlugin expects:
        {
            "value":    "the thing to remember",
            "saved_at": "2026-03-18 14:30"
        }

    Using this function means:
    - Format is always correct — MemoryPlugin.forget() will never crash
    - Key collisions are handled — existing key gets updated, not duplicated
    - No plugin needs to know the internal memory structure

    Args:
        uid:   Firebase user ID
        key:   Memory key (e.g. "physics_exam", "project_deadline")
               Will be lowercased and spaces replaced with underscores
        value: The content to remember

    Returns:
        True on success, False on failure

    Example:
        save_single_memory(uid, "physics exam", "is on May 20 at 2pm")
        # Saves as memories["physics_exam"] = {"value": "is on May 20 at 2pm", ...}
    """
    if not uid or not key or not value:
        logger.warning(f"save_single_memory called with empty args: uid={uid} key={key}")
        return False

    # Normalise key — lowercase, underscores, max 30 chars
    clean_key = key.lower().strip().replace(" ", "_")[:30]

    try:
        # Load existing memories
        user_data = get_user_data(uid) or {}
        memories  = user_data.get("memories", {}) or {}

        # Write in the correct format
        memories[clean_key] = {
            "value":    value,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

        success = save_memories(uid, memories)
        if success:
            logger.info(f"Single memory saved — uid: {uid} key: '{clean_key}'")
        return success

    except Exception as e:
        logger.error(f"save_single_memory failed for uid '{uid}': {e}")
        return False

# ─────────────────────────────────────────────
# SAVE IDENTITY
# ─────────────────────────────────────────────

def save_identity(uid: str, identity: Dict) -> bool:
    """
    Save a user's identity to Supabase.
    Overwrites the entire identity field.
    """
    if not _check():
        return False
    assert _client is not None
    try:
        _client.table("user_data").update({
            "identity": identity
        }).eq("uid", uid).execute()
        logger.debug(f"Identity saved for uid: {uid}")
        return True
    except Exception as e:
        logger.error(f"save_identity failed for uid '{uid}': {e}")
        return False

# ─────────────────────────────────────────────
# GET OR CREATE USER
# ─────────────────────────────────────────────

def get_or_create_user(uid: str, email: str) -> Dict:
    """
    Fetch user data, creating the row if it doesn't exist yet.
    Returns the user data dict always.
    This is the main function called on WebSocket connect.
    """
    data = get_user_data(uid)
    if data is None:
        create_user(uid, email)
        return {"uid": uid, "email": email, "memories": {}, "identity": {}}
    return data