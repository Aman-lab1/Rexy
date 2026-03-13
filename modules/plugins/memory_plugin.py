"""
REXY MEMORY PLUGIN
Lets Rexy remember things you tell her — persisted to memory.json.
Works across sessions, not just within a conversation.

Handles:
- "remember that my exam is on March 15"
- "remember my WiFi password is 12345"
- "what do you remember about my exam?"
- "what did I tell you about WiFi?"
- "forget about my exam"
- "show me everything you remember"
- "forget everything"
"""

import re
import json
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.memory")

# Where memories are stored on disk
MEMORY_FILE = "memories.json"


class MemoryPlugin(RexyPlugin):
    """
    Persistent key-value memory for Rexy.
    Saves to memories.json so memories survive restarts.

    Memory structure in JSON:
    {
      "exam": {
        "value": "my exam is on March 15",
        "saved_at": "2026-03-08 03:00:00"
      },
      "wifi": {
        "value": "WiFi password is 12345",
        "saved_at": "2026-03-08 03:01:00"
      }
    }
    """

    def __init__(self):
        # Load existing memories from disk on startup
        self._memories: Dict[str, Dict] = self._load_memories()

    @property
    def intent_name(self) -> str:
        return "MEMORY"

    @property
    def description(self) -> str:
        return "Remember, recall, and forget things across sessions"

    @property
    def risk_level(self) -> str:
        return "low"

    @property
    def intent_examples(self) -> List[str]:
        return [
            "remember that my exam is on March 15",
            "what do you remember about my exam",
            "forget about my exam",
            "show me everything you remember",
            "remember my sister's birthday is June 3",
        ]

    # ── Main execute ──
    def execute(self, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Detect whether user wants to SAVE, RECALL, FORGET, or LIST memories.
        Routes to the right handler.
        """
        message_lower = message.lower().strip()

        # ── FORGET ALL ──
        if re.search(r'\b(forget|clear|delete|wipe)\s+(all|everything)\b', message_lower):
            return self._forget_all()

        # ── FORGET SPECIFIC ──
        forget_match = re.search(
            r'\b(forget|delete|remove|clear)\s+(?:about\s+)?(?:my\s+)?(.+?)(?:\s*$|\s*\.)',
            message_lower
        )
        if forget_match:
            topic = forget_match.group(2).strip()
            return self._forget(topic)

        # ── LIST ALL ──
        if re.search(r'\b(show|list|what do you remember|everything you remember|all memories)\b', message_lower):
            return self._list_all()

        # ── RECALL SPECIFIC ──
        recall_match = re.search(
            r'\b(what|recall|remember|remind me|do you know)\b.{0,30}\b(?:about|regarding|my)\s+(.+?)(?:\?|$|\.)',
            message_lower
        )
        if recall_match:
            topic = recall_match.group(2).strip()
            return self._recall(topic)

        # ── SAVE ──
        save_match = re.search(
            r'\b(remember|save|note|keep in mind|don\'t forget)\s+(?:that\s+)?(.+)',
            message_lower
        )
        if save_match:
            content = save_match.group(2).strip()
            return self._save(content, message)

        # ── FALLBACK: try to recall if message seems like a question ──
        if "?" in message or message_lower.startswith("what"):
            return {
                "reply": "🧠 What would you like me to remember or recall? Try: 'remember that...' or 'what do you remember about...'",
                "emotion": "neutral",
                "state": "speaking"
            }

        # ── DEFAULT: treat as save ──
        return self._save(message, message)

    # ─────────────────────────────────────────────
    # SAVE
    # ─────────────────────────────────────────────
    def _save(self, content: str, original_message: str) -> Dict[str, Any]:
        """
        Save a memory. Extracts a short key from the content for easy recall.
        "my exam is on March 15" → key: "exam", value: full content
        """
        if not content or len(content) < 3:
            return {
                "reply": "🧠 What should I remember? Try: 'remember that my exam is on Friday'",
                "emotion": "neutral",
                "state": "speaking"
            }

        # Generate a short key from the first meaningful word(s)
        key = self._generate_key(content)

        self._memories[key] = {
            "value":    content,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        self._save_memories()

        logger.info(f"Memory saved: key='{key}' value='{content[:50]}'")
        return {
            "reply": f"🧠 Got it! I'll remember: '{content}' (saved as '{key}')",
            "emotion": "happy",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # RECALL
    # ─────────────────────────────────────────────
    def _recall(self, topic: str) -> Dict[str, Any]:
        """
        Find memories that match the topic.
        Searches both keys and values for partial matches.
        """
        if not self._memories:
            return {
                "reply": "🧠 I don't have any memories saved yet! Tell me something to remember.",
                "emotion": "neutral",
                "state": "speaking"
            }

        topic_lower = topic.lower().strip()
        matches = []

        for key, data in self._memories.items():
            # Check if topic appears in key or value
            if topic_lower in key.lower() or topic_lower in data["value"].lower():
                matches.append((key, data))

        if not matches:
            return {
                "reply": f"🧠 I don't have anything saved about '{topic}'. Want me to remember something about it?",
                "emotion": "neutral",
                "state": "speaking"
            }

        # Format matches
        if len(matches) == 1:
            key, data = matches[0]
            return {
                "reply": f"🧠 About '{topic}': {data['value']}\n_(saved {data['saved_at']})_",
                "emotion": "neutral",
                "state": "speaking"
            }
        else:
            lines = [f"🧠 Found {len(matches)} memories about '{topic}':"]
            for key, data in matches:
                lines.append(f"• {data['value']} _(saved {data['saved_at']})_")
            return {
                "reply": "\n".join(lines),
                "emotion": "neutral",
                "state": "speaking"
            }

    # ─────────────────────────────────────────────
    # FORGET SPECIFIC
    # ─────────────────────────────────────────────
    def _forget(self, topic: str) -> Dict[str, Any]:
        """Delete memories matching the topic. Supports 'forget X and Y'."""
        # Split on ' and ' to handle multiple topics at once
        topics = [t.strip() for t in re.split(r'\s+and\s+', topic.lower())]
        
        all_deleted = []
        for topic_lower in topics:
            for key in list(self._memories.keys()):
                if topic_lower in key.lower() or topic_lower in self._memories[key]["value"].lower():
                    del self._memories[key]
                    all_deleted.append(key)

        if not all_deleted:
            return {
                "reply": f"🧠 I don't have any memories about '{topic}' to forget.",
                "emotion": "neutral",
                "state": "speaking"
            }

        self._save_memories()
        logger.info(f"Memory forgotten: {all_deleted}")
        return {
            "reply": f"🧠 Forgotten! Removed {len(all_deleted)} memory/memories.",
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # FORGET ALL
    # ─────────────────────────────────────────────
    def _forget_all(self) -> Dict[str, Any]:
        """Clear all memories."""
        count = len(self._memories)
        if count == 0:
            return {
                "reply": "🧠 Nothing to forget — memory is already empty!",
                "emotion": "neutral",
                "state": "speaking"
            }

        self._memories.clear()
        self._save_memories()
        logger.info("All memories cleared.")
        return {
            "reply": f"🧠 Done! Cleared all {count} memories. Fresh start.",
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # LIST ALL
    # ─────────────────────────────────────────────
    def _list_all(self) -> Dict[str, Any]:
        """Show everything currently remembered."""
        if not self._memories:
            return {
                "reply": "🧠 I don't remember anything yet! Tell me something: 'remember that...'",
                "emotion": "neutral",
                "state": "speaking"
            }

        lines = [f"🧠 I remember {len(self._memories)} thing(s):\n"]
        for key, data in self._memories.items():
            lines.append(f"• [{key}] {data['value']} _(saved {data['saved_at']})_")

        return {
            "reply": "\n".join(lines),
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # KEY GENERATION
    # ─────────────────────────────────────────────
    def _generate_key(self, content: str) -> str:
        """
        Generate a short, readable key from the memory content.
        "my exam is on March 15" → "exam"
        "WiFi password is 12345" → "wifi_password"
        """
        # Remove common filler words
        stopwords = {
            "my", "is", "on", "the", "a", "an", "are", "was", "were",
            "that", "this", "it", "i", "me", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "and", "or", "but", "in", "at", "to",
            "for", "of", "with", "by", "ya", "yep", "yeah", "thats",
            "just", "like", "so", "too", "also", "want", "wanted",
            "gonna", "gotta", "btw", "its", "its", "im", "ive", "ill"
        }
        
        words = re.findall(r'[a-zA-Z]+', content.lower())
        meaningful = [w for w in words if w not in stopwords and len(w) > 2]

        if not meaningful:
            # Fallback: use timestamp
            return f"memory_{datetime.now().strftime('%H%M%S')}"

        # Use first 2 meaningful words as key
        key = "_".join(meaningful[:2])

        # If key already exists, append a number
        base_key = key
        counter  = 2
        while key in self._memories:
            key = f"{base_key}_{counter}"
            counter += 1

        return key

    # ─────────────────────────────────────────────
    # DISK PERSISTENCE
    # ─────────────────────────────────────────────
    def _load_memories(self) -> Dict:
        """Load memories from disk on startup."""
        try:
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} memories from disk.")
                    return data
        except Exception as e:
            logger.warning(f"Memory load failed (starting fresh): {e}")
        return {}

    def _save_memories(self) -> None:
        """Persist memories to disk. Called after every change."""
        try:
            with open(MEMORY_FILE, 'w') as f:
                json.dump(self._memories, f, indent=2)
        except Exception as e:
            logger.warning(f"Memory save failed: {e}")
