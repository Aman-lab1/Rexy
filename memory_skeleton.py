# memory_skeleton.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

# 1️⃣ Chat Memory (short-term)
@dataclass
class ChatMemory:
    last_user_message: Optional[str] = None
    last_rexy_reply: Optional[str] = None
    turn_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expired: bool = False  # placeholder flag, not used yet


# 2️⃣ Emotion / Advisor Memory
@dataclass
class EmotionMemory:
    emotion_tag: Optional[str] = None   # "happy", "bored", "neutral", ...
    source: Optional[str] = None        # "rule", "advisor", "ui", ...
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_turns: int = 0                  # placeholder only, no logic yet


# 3️⃣ System Context Memory (read-only snapshot)
@dataclass
class SystemContextMemory:
    last_intent: Optional[str] = None
    last_risk_level: Optional[str] = None
    last_execution_status: Optional[str] = None
    # Mirrors existing context_state but does NOT replace it.


# 🔹 Global in-module store (scoped, disposable)
_MEMORY_STORE: Dict[str, Any] = {
    "chat": None,
    "emotion": None,
    "system": None,
}


def init_memory() -> None:
    """
    Initialize empty memory structures.
    Safe to call multiple times.
    Does not affect any existing pipeline.
    """
    _MEMORY_STORE["chat"] = ChatMemory()
    _MEMORY_STORE["emotion"] = EmotionMemory()
    _MEMORY_STORE["system"] = SystemContextMemory()


def write_memory(mem_type: str, data: Dict[str, Any]) -> None:
    """
    Best-effort setter.
    - Silently returns if mem_type is unknown.
    - Silently returns if memory not initialized.
    - Only updates known fields; ignores extra keys.
    - Never throws; never blocks.
    """
    if mem_type not in _MEMORY_STORE:
        return
    obj = _MEMORY_STORE.get(mem_type)
    if obj is None:
        return

    for key, value in data.items():
        if hasattr(obj, key):
            setattr(obj, key, value)

    if hasattr(obj, "updated_at"):
        setattr(obj, "updated_at", datetime.utcnow())


def read_memory(mem_type: str) -> Optional[Any]:
    """
    Read-only accessor.
    - Returns a dataclass instance or None.
    - Never raises on unknown type.
    """
    return _MEMORY_STORE.get(mem_type, None)


def clear_memory(mem_type: str) -> None:
    """
    Disposable memory cleaner.
    - Resets the given memory type to a fresh instance.
    - Safe no-op for unknown types.
    """
    if mem_type == "chat":
        _MEMORY_STORE["chat"] = ChatMemory()
    elif mem_type == "emotion":
        _MEMORY_STORE["emotion"] = EmotionMemory()
    elif mem_type == "system":
        _MEMORY_STORE["system"] = SystemContextMemory()
    else:
        return
