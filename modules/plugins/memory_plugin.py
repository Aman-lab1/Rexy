"""
REXY MEMORY PLUGIN v2.0
Per-user persistent memory stored in Supabase.
No more shared memories.json — each user gets their own memory.

Handles:
- "remember that my exam is on March 15"
- "remember my WiFi password is 12345"
- "what do you remember about my exam?"
- "forget about my exam"
- "show me everything you remember"
- "forget everything"
"""

import re
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.plugin_base import RexyPlugin
import supabase_db
import pattern_detector


logger = logging.getLogger("rexy.memory")


class MemoryPlugin(RexyPlugin):
    """
    Per-user persistent memory stored in Supabase.
    Memories are loaded from Supabase on each execute() call
    and saved back after every change.

    Memory structure (stored as JSONB in Supabase):
    {
      "exam": {
        "value": "my exam is on March 15",
        "saved_at": "2026-03-08 03:00:00"
      }
    }
    """

    # No __init__ needed — no shared state anymore

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
        Load this user's memories from Supabase, process request, save if changed.
        """
        # Get uid from session state
        uid = state.get("uid", "")
        if not uid:
            return {
                "reply": "🧠 Memory unavailable — not authenticated.",
                "emotion": "neutral",
                "state": "speaking"
            }

        # Load this user's memories from Supabase
        memories = self._load(uid)

        message_lower = message.lower().strip()
        # ── ABOUT ME (from SmartGate args or message pattern) ──
        if args.get("action") == "about_me" or re.search(
            r'\b(what do you know|what do you remember|tell me|what have you learned)\b.{0,25}\b(about me|about myself)\b'
            r'|\b(what.?s|whats|what is)\s+my\s+(name|birthday|bday|age)\b'
            r'|\bdo you know my (name|birthday|bday)\b',
            message_lower
        ):
            return self._about_me(uid, memories)
        # ── FORGET ALL ──
        if re.search(r'\b(forget|clear|delete|wipe)\s+(all|everything)\b', message_lower):
            return self._forget_all(uid, memories)

        # ── FORGET SPECIFIC ──
        forget_match = re.search(
            r'\b(forget|delete|remove|clear)\s+(?:about\s+)?(?:my\s+)?(.+?)(?:\s*$|\s*\.)',
            message_lower
        )
        if forget_match:
            topic = forget_match.group(2).strip()
            return self._forget(uid, memories, topic)

        # ── LIST ALL ──
        if re.search(r'\b(show|list|what do you remember|everything you remember|all memories)\b', message_lower):
            return self._list_all(memories)

        # ── SAVE — must come before RECALL ──
        # "remember that X" should save, not recall
        save_match = re.search(
            r'\b(remember|save|note|keep in mind|don\'t forget)\s+(?:that\s+)?(.+)',
            message_lower
        )
        if save_match:
            content = save_match.group(2).strip()
            return self._save(uid, memories, content)
        
        # ── ABOUT ME ──
        if re.search(r'\b(what do you know|what do you remember|tell me|what have you learned)\b.{0,25}\b(about me|about myself)\b', message_lower) \
        or re.search(r'\b(what|whats|what\'s)\s+(is\s+)?my\s+(name|birthday|bday)\b', message_lower) \
        or re.search(r'\bdo you know my (name|birthday)\b', message_lower):
            return self._about_me(uid, memories)
        
        # ── RECALL SPECIFIC ──
        recall_match = re.search(
            r'\b(what|recall|remind me|do you know)\b.{0,30}\b(?:about|regarding|my)\s+(.+?)(?:\?|$|\.)',
            message_lower
        )
        if recall_match:
            topic = recall_match.group(2).strip()
            return self._recall(memories, topic)

        # ── FALLBACK ──
        if "?" in message or message_lower.startswith("what"):
            return {
                "reply": "🧠 What would you like me to remember or recall? Try: 'remember that...' or 'what do you remember about...'",
                "emotion": "neutral",
                "state": "speaking"
            }

        return self._save(uid, memories, message)

    # ─────────────────────────────────────────────
    # SUPABASE LOAD / SAVE
    # ─────────────────────────────────────────────

    def _load(self, uid: str) -> Dict:
        """Load this user's memories from Supabase."""
        try:
            user_data = supabase_db.get_user_data(uid)
            if user_data and user_data.get("memories"):
                return user_data["memories"]
        except Exception as e:
            logger.warning(f"Memory load failed for uid '{uid}': {e}")
        return {}

    def _persist(self, uid: str, memories: Dict) -> None:
        """Save this user's memories to Supabase."""
        try:
            supabase_db.save_memories(uid, memories)
        except Exception as e:
            logger.warning(f"Memory save failed for uid '{uid}': {e}")

    # ─────────────────────────────────────────────
    # SAVE
    # ─────────────────────────────────────────────

    def _save(self, uid: str, memories: Dict, content: str) -> Dict[str, Any]:
        if not content or len(content) < 3:
            return {
                "reply": "🧠 What should I remember? Try: 'remember that my exam is on Friday'",
                "emotion": "neutral",
                "state": "speaking"
            }

        key = self._generate_key(content, memories)
        memories[key] = {
            "value":    content,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        self._persist(uid, memories)

        logger.info(f"Memory saved for uid '{uid}': key='{key}' value='{content[:50]}'")
        return {
            "reply": f"🧠 Got it! I'll remember: '{content}' (saved as '{key}')",
            "emotion": "happy",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # RECALL
    # ─────────────────────────────────────────────

    def _recall(self, memories: Dict, topic: str) -> Dict[str, Any]:
        if not memories:
            return {
                "reply": "🧠 I don't have any memories saved yet! Tell me something to remember.",
                "emotion": "neutral",
                "state": "speaking"
            }

        topic_lower = topic.lower().strip()
        matches = []

        for key, data in memories.items():
            if topic_lower in key.lower() or topic_lower in data["value"].lower():
                matches.append((key, data))

        if not matches:
            return {
                "reply": f"🧠 I don't have anything saved about '{topic}'. Want me to remember something about it?",
                "emotion": "neutral",
                "state": "speaking"
            }

        if len(matches) == 1:
            key, data = matches[0]
            return {
                "reply": f"🧠 About '{topic}': {data['value']}\n(saved {data['saved_at']})",
                "emotion": "neutral",
                "state": "speaking"
            }

        lines = [f"🧠 Found {len(matches)} memories about '{topic}':"]
        for key, data in matches:
            lines.append(f"• {data['value']} (saved {data['saved_at']})")
        return {
            "reply": "\n".join(lines),
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # FORGET SPECIFIC
    # ─────────────────────────────────────────────

    def _forget(self, uid: str, memories: Dict, topic: str) -> Dict[str, Any]:
        topics = [t.strip() for t in re.split(r'\s+and\s+', topic.lower())]

        all_deleted = []
        for topic_lower in topics:
            for key in list(memories.keys()):
                if topic_lower in key.lower() or topic_lower in memories[key]["value"].lower():
                    del memories[key]
                    all_deleted.append(key)

        if not all_deleted:
            return {
                "reply": f"🧠 I don't have any memories about '{topic}' to forget.",
                "emotion": "neutral",
                "state": "speaking"
            }

        self._persist(uid, memories)
        logger.info(f"Memory forgotten for uid '{uid}': {all_deleted}")
        return {
            "reply": f"🧠 Forgotten! Removed {len(all_deleted)} memory/memories.",
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # FORGET ALL
    # ─────────────────────────────────────────────

    def _forget_all(self, uid: str, memories: Dict) -> Dict[str, Any]:
        count = len(memories)
        if count == 0:
            return {
                "reply": "🧠 Nothing to forget — memory is already empty!",
                "emotion": "neutral",
                "state": "speaking"
            }

        memories.clear()
        self._persist(uid, memories)
        logger.info(f"All memories cleared for uid '{uid}'.")
        return {
            "reply": f"🧠 Done! Cleared all {count} memories. Fresh start.",
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # LIST ALL
    # ─────────────────────────────────────────────

    def _list_all(self, memories: Dict) -> Dict[str, Any]:
        if not memories:
            return {
                "reply": "🧠 I don't remember anything yet! Tell me something: 'remember that...'",
                "emotion": "neutral",
                "state": "speaking"
            }

        lines = [f"🧠 I remember {len(memories)} thing(s):\n"]
        for key, data in memories.items():
            lines.append(f"• [{key}] {data['value']} (saved {data['saved_at']})")

        return {
            "reply": "\n".join(lines),
            "emotion": "neutral",
            "state": "speaking"
        }
    # ─────────────────────────────────────────────
    # ABOUT ME — combines identity + patterns
    # ─────────────────────────────────────────────

    def _about_me(self, uid: str, memories: Dict) -> Dict[str, Any]:

        parts = []
        
        # Pull identity column for name
        try:
            user_data = supabase_db.get_user_data(uid) or {}
            identity  = user_data.get("identity") or {}
        except Exception:
            identity = {}

        name = identity.get("name") or None
        print("DEBUG identity:", identity, "| name:", name)

        # Fallback: scan memories for name if identity is empty
        if not name:
            for key, data in memories.items():
                if key == "patterns":
                    continue
                if "name" in key.lower():
                    val = data.get("value", "")
                    # extract just the name word(s)
                    m = re.search(r'(?:my name is|name[:\s]+)\s*([A-Za-z]+)', val, re.IGNORECASE)
                    name = m.group(1).capitalize() if m else val
                    break

        if name:
            parts.append(f"your name is {name}")

        # Birthday — extract date from raw sentence
        bday_data = memories.get("birthday", {})
        if bday_data:
            bday_val = bday_data.get("value", "")
            date_match = re.search(
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{4})?)',
                bday_val, re.IGNORECASE
            )
            if date_match:
                parts.append(f"your birthday is on {date_match.group(1)}")

        # Patterns
        try:
            patterns = memories.get("patterns") or pattern_detector.get_patterns(uid) or {}
            active_time = patterns.get("active_time", "unknown")
            top_topics  = patterns.get("top_topics", [])
            if active_time and active_time != "unknown":
                parts.append(f"you're usually active during the {active_time}")
            if top_topics:
                parts.append(f"you mostly talk to me about {', '.join(top_topics)}")
        except Exception as e:
            logger.warning(f"_about_me: pattern fetch failed — {e}")

        # Other saved memories (skip system keys)
        SYSTEM_KEYS = {"patterns", "reflection_used_today"}
        other_count = sum(1 for k in memories if k not in SYSTEM_KEYS
                        and "name" not in k.lower()
                        and k != "birthday")

        if not parts:
            return {
                "reply": "Honestly, I don't know much about you yet. Tell me something — like your name, or anything you'd like me to remember.",
                "emotion": "neutral",
                "state": "speaking"
            }

        reply = "Here's what I know — " + ", ".join(parts) + "."
        if other_count > 0:
            reply += f" I've also got {other_count} other thing{'s' if other_count > 1 else ''} saved for you."
        
        return {
            "reply": reply,
            "emotion": "happy",
            "state": "speaking"
        }
    # ─────────────────────────────────────────────
    # KEY GENERATION
    # ─────────────────────────────────────────────

    def _generate_key(self, content: str, memories: Dict) -> str:
        stopwords = {
            "my", "is", "on", "the", "a", "an", "are", "was", "were",
            "that", "this", "it", "i", "me", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "and", "or", "but", "in", "at", "to",
            "for", "of", "with", "by", "ya", "yep", "yeah", "thats",
            "just", "like", "so", "too", "also", "want", "wanted",
            "gonna", "gotta", "btw", "its", "im", "ive", "ill"
        }

        words = re.findall(r'[a-zA-Z]+', content.lower())
        meaningful = [w for w in words if w not in stopwords and len(w) > 2]

        if not meaningful:
            return f"memory_{datetime.now().strftime('%H%M%S')}"

        key = "_".join(meaningful[:2])
        base_key = key
        counter = 2
        while key in memories:
            key = f"{base_key}_{counter}"
            counter += 1

        return key