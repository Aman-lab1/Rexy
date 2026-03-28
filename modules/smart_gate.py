"""
REXY SMART GATE v1.0
Layer 0 of the THINK stage — runs before Groq is ever called.

Architecture:
    User message
        ↓
    SmartGate.check()          ← You are here
        ├── Layer 1: Exact commands    (dict lookup, O(1))
        ├── Layer 2: Regex patterns    (ordered, first-match wins)
        └── returns None → Groq fires  (only for ambiguous messages)

Why this matters:
    - "what time is it" should NEVER cost a Groq token
    - "weather in Ahmedabad" should NEVER cost a Groq token
    - "reset" should NEVER cost a Groq token
    - "explain black holes" SHOULD — that needs real reasoning

Author: Aman (EEE @ Ahmedabad University)
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("rexy.smart_gate")


# ─────────────────────────────────────────────────────────────
# GATE STATISTICS
# Tracks how many messages each layer handles.
# Call SmartGate.stats() to see how well the gate is working.
# ─────────────────────────────────────────────────────────────
_stats = {
    "total_checked":   0,
    "exact_hits":      0,
    "pattern_hits":    0,
    "llm_passthrough": 0,
}


class SmartGate:
    """
    Deterministic first-pass intent router.

    Returns full intent_data dict if the message is simple enough to
    route without the LLM. Returns None when Groq is genuinely needed.

    Usage:
        result = SmartGate.check(message)
        if result:
            # Use result directly — no LLM needed
        else:
            # Fall through to IntentDetector (Groq)
    """

    # ──────────────────────────────────────────────────────────
    # LAYER 1: EXACT COMMANDS
    # These are the most common, ultra-simple commands.
    # Pure dict lookup — O(1). No regex overhead.
    # Keys are lowercase stripped. Values are intent strings.
    # ──────────────────────────────────────────────────────────
    EXACT_COMMANDS: Dict[str, str] = {
        # Time
        "time":               "GET_TIME",
        "what time":          "GET_TIME",
        "what's the time":    "GET_TIME",
        "whats the time":     "GET_TIME",
        "clock":              "GET_TIME",
        "current time":       "GET_TIME",

        # Greetings
        "hi":                 "GREET",
        "hello":              "GREET",
        "hey":                "GREET",
        "hey rexy":           "GREET",
        "hi rexy":            "GREET",
        "hello rexy":         "GREET",
        "yo":                 "GREET",
        "sup":                "GREET",
        "good morning":       "GREET",
        "good evening":       "GREET",
        "good night":         "GREET",
        "what's up":          "GREET",
        "whats up":           "GREET",
        "howdy":              "GREET",

        # Reset
        "reset":              "RESET",
        "clear":              "RESET",
        "restart":            "RESET",
        "start over":         "RESET",
        "start fresh":        "RESET",
        "clear everything":   "RESET",
        "fresh start":        "RESET",

        # Files
        "list files":         "LIST_FILES",
        "show files":         "LIST_FILES",
        "files":              "LIST_FILES",
        "my files":           "LIST_FILES",
        "inbox":              "FILE_READ",

        # System
        "sysinfo":            "SYSTEM_INFO",
        "system info":        "SYSTEM_INFO",
        "system information": "SYSTEM_INFO",
        "cpu":                "SYSTEM_INFO",
        "ram":                "SYSTEM_INFO",
        "battery":            "SYSTEM_INFO",
        "disk":               "SYSTEM_INFO",
        "cpu usage":          "SYSTEM_INFO",
        "ram usage":          "SYSTEM_INFO",
        "battery level":      "SYSTEM_INFO",
        "disk space":         "SYSTEM_INFO",
        "storage":            "SYSTEM_INFO",

        # Music
        "music":              "MUSIC",
        "play music":         "MUSIC",
        "play something":     "MUSIC",
        "play songs":         "MUSIC",

        # Advisor
        "bored":              "ADVISOR",
        "i'm bored":          "ADVISOR",
        "im bored":           "ADVISOR",
        "i am bored":         "ADVISOR",
        "nothing to do":      "ADVISOR",

        # Weather (no city = open ended)
        "weather":            "WEATHER",

        # Calendar
        "my calendar":              "CALENDAR",
        "open calendar":            "CALENDAR",
        "show calendar":            "CALENDAR",
        "check calendar":           "CALENDAR",
        "calendar today":           "CALENDAR",
        "what's on my calendar":    "CALENDAR",
        "whats on my calendar":     "CALENDAR",
        "today's schedule":         "CALENDAR",
        "todays schedule":          "CALENDAR",
        "my schedule":              "CALENDAR",
        "my schedule today":        "CALENDAR",
        "my schedule this week":    "CALENDAR",

        # Screenshots
        "screenshot":           "COMPUTER",
        "take a screenshot":    "COMPUTER",
        "take screenshot":      "COMPUTER",
        # Volume
        "volume up":            "COMPUTER",
        "volume down":          "COMPUTER",
        "mute":                 "COMPUTER",
        "unmute":               "COMPUTER",
        "what's the volume":    "COMPUTER",
        "whats the volume":     "COMPUTER",
        "get volume":           "COMPUTER",
        "check volume":         "COMPUTER",
        "current volume":       "COMPUTER",
        # Brightness
        "brightness up":        "COMPUTER",
        "brightness down":      "COMPUTER",
        "what's the brightness":"COMPUTER",
        "get brightness":       "COMPUTER",
        "check brightness":     "COMPUTER",
        "current brightness":   "COMPUTER",
        # Apps
        "list apps":            "COMPUTER",
        "what apps can you open":"COMPUTER",
    }

    # ──────────────────────────────────────────────────────────
    # LAYER 2: REGEX PATTERNS
    # Checked in ORDER — first match wins. Put more specific
    # patterns above broader ones to avoid false positives.
    #
    # Format: (pattern, intent, args_or_None)
    #   - args = {} means no extraction needed (args are empty)
    #   - args = None means _extract_args() will be called
    # ──────────────────────────────────────────────────────────
    PATTERNS: List[Tuple[str, str, Optional[Dict[str, Any]]]] = [
        # ── CALCULATOR ──────────────────────────────────────────
        # Must be first — math is ultra-precise, no ambiguity
        (r'\d[\d\s]*[\+\-\*\/][\d\s]*\d',       "CALCULATOR",   {}),
        (r'\b(calc|calculate)\b',                 "CALCULATOR",   {}),

        # ── TIME ────────────────────────────────────────────────
        # "what time is it in Tokyo" → CHAT (timezone question, not local time)
        # Order matters: check "in <city>" BEFORE plain time
        (r'\bwhat time is it\s+in\s+\w+',         "CHAT",         {}),
        (r'\bwhat time is it\b',                   "GET_TIME",     {}),
        (r'\b(tell me the time|show me the time)\b', "GET_TIME",  {}),

        # ── WEATHER ─────────────────────────────────────────────
        (r'\b(weather|temperature|forecast|is it raining|'
         r'will it rain|do i need an umbrella|how.s the weather)\b',
                                                   "WEATHER",     None),  # extracts city

        # ── SYSTEM INFO ─────────────────────────────────────────
        # Must come before MEMORY to catch "memory usage" correctly
        (r'\b(memory\s+usage|cpu\s+usage|ram\s+usage|disk\s+space|'
         r'battery\s+(level|status|percentage)|system\s+(info|stats|status)|'
         r'uptime|processor\s+speed|storage\s+usage|how\s+much\s+(ram|cpu))\b',
                                                   "SYSTEM_INFO", {}),

        # ── FILES ───────────────────────────────────────────────
        (r'\b(list\s+(my\s+)?files|show\s+(my\s+)?files|'
         r'what.?s in (the |my )?folder|folder contents)\b',
                                                   "LIST_FILES",  {}),
        (r'\b(read|open|load|show me)\s+\w+\.(txt|pdf|py|js|md|csv|json)\b',
                                                   "FILE_READ",   None),  # extracts filename
        (r'\binbox\b',                             "FILE_READ",   {}),

        # ── WEB SEARCH ──────────────────────────────────────────
        # Must be explicit — "search X", "google X", "look up X"
        # Do NOT match general questions (those go to CHAT via Groq)
        (r'^\s*(search|look\s*up|google|find\s+info|find\s+information)\b',
                                                   "WEB_SEARCH",  None),  # extracts query
        # ── ABOUT ME ────────────────────────────────────────────────
        # Must be BEFORE the generic MEMORY pattern
        (
        r'\b(what do you know|what do you remember|tell me|what have you learned)\b.{0,25}\b(about me|about myself)\b'
        r'|\b(what.?s|whats|what is|when is|when.?s)\s+my\s+(name|birthday|bday|birthdate|birth date|age)\b'
        r'|\bdo you know my (name|birthday|bday|birthdate)\b',
            "MEMORY",
            {"action": "about_me"}
        ),
        # ── MEMORY ──────────────────────────────────────────────
        # Only explicit memory phrases — "remember that", "remind me"
        # Do NOT match "my name is X" (that's CHAT for ChatHandler to handle)
        (r'\b(remember\s+that|remind\s+me\s+(to|that|about)|'
         r'don.?t\s+forget|what\s+do\s+you\s+remember|'
         r'forget\s+about|what\s+did\s+i\s+tell\s+you\s+about)\b',
                                                   "MEMORY",      None),  # extracts action/content

        # ── RESET ───────────────────────────────────────────────
        (r'\b(reset|clear\s+everything|start\s+(fresh|over)|'
         r'forget\s+everything\s+and\s+restart)\b',
                                                   "RESET",       {}),

        # ── CALENDAR — VIEW ─────────────────────────────────────
        (
            r'\b(what.?s\s+on\s+my\s+calendar|show\s+(my\s+)?schedule|'
            r'what\s+do\s+i\s+have\s+(today|tomorrow|this\s+week)|'
            r'check\s+(my\s+)?calendar|view\s+(my\s+)?calendar|'
            r'my\s+events\s+(today|tomorrow|this\s+week))\b',
            "CALENDAR",
            None
        ),
 
        # ── CALENDAR — ADD ───────────────────────────────────────────
        (
            r'\b(add\s+(my\s+|an?\s+|the\s+)?(\w+\s+)?(exam|appointment|meeting|'
            r'event|reminder|class|lecture|test|interview|call|session|'
            r'birthday|deadline|assignment|presentation|seminar|workshop)|'
            r'schedule\s+(an?\s+|my\s+)?(\w+\s+)?(exam|appointment|meeting|'
            r'event|reminder|class|call)|'
            r'set\s+(a\s+|an?\s+)?reminder\s+for|'
            r'put\s+.+\s+on\s+(my\s+)?calendar|'
            r'add\s+to\s+(my\s+)?calendar)\b',
            "CALENDAR",
            None
        ),
 
        # ── CALENDAR — DELETE ────────────────────────────────────────
        (
            r'\b(cancel|delete|remove)\s+(my\s+|the\s+|an?\s+)?(\w+\s+)?(exam|appointment|meeting|'
            r'event|reminder|class|lecture|test|interview|call|session|birthday|deadline)\b',
            "CALENDAR",
            None
        ),
 
        # ── CALENDAR — BOTH (memory + calendar) ──────────────────
        (
            r'\b(remember|remind\s+me).{1,60}(add|calendar|schedule)\b|'
            r'\b(add|schedule).{1,60}(remember|memory|remind)\b|'
            r'\badd\s+to\s+both\b',
            "CALENDAR",
            None
        ),

        # ── GREETINGS ───────────────────────────────────────────
        # Only pure greetings — no other request attached
        # These are short messages so a word-boundary check is enough
        (r'^(hi|hello|hey|yo|sup|howdy|hiya|'
         r'good\s+(morning|evening|night|afternoon)|'
         r'what.?s\s+up|how\s+are\s+you)\s*[!?.]*\s*$',
                                                   "GREET",       {}),

        # ── MUSIC ───────────────────────────────────────────────
        (r'\b(play\s+(some\s+)?music|put\s+on\s+(a\s+)?playlist|'
         r'play\s+something|chill\s+songs|play\s+songs)\b',
                                                   "MUSIC",       {}),

        # ── ADVISOR ─────────────────────────────────────────────
        (r'\b(i.?m\s+(so\s+)?bored|i\s+am\s+(so\s+)?bored|'
         r'nothing\s+to\s+do|suggest\s+something\s+fun|'
         r'what\s+should\s+i\s+do)\b',
                                                   "ADVISOR",     {}),

        # ── COMPUTER — OPEN APP ──────────────────────────────────
        (
            r'\b(open|launch|start|run)\s+\w[\w\s]{1,30}$',
            "COMPUTER",
            None
        ),
    
        # ── COMPUTER — VOLUME ────────────────────────────────────
        (
            r'\b(set\s+volume|volume\s+(to|up|down|at)|\bmute\b|'
            r'turn\s+(up|down)\s+the\s+volume|increase\s+volume|'
            r'decrease\s+volume|lower\s+volume|raise\s+volume)\b',
            "COMPUTER",
            None
        ),
    
        # ── COMPUTER — BRIGHTNESS ───────────────────────────────
        (
            r'\b(set\s+brightness|brightness\s+(to|up|down|at)|'
            r'increase\s+brightness|decrease\s+brightness|'
            r'lower\s+brightness|raise\s+brightness|dim\s+(the\s+)?screen|'
            r'brightness|screen\s+brightness|'
            r'(increase|decrease|lower|raise|set)\s+(the\s+)?brightness)\b',
            "COMPUTER",
            None
        ),
    
        # ── COMPUTER — SCREENSHOT ───────────────────────────────
        (
            r'\b(take\s+a?\s+screenshot|capture\s+(the\s+)?screen|'
            r'screen\s+capture|screenshot\s+(called|named|save))\b',
            "COMPUTER",
            None
        ),

        # ── REXY STATUS ─────────────────────────────────────────────
        (
            r'^\s*(who|what)\s+are\s+you\b'
            r'|\bwhat\s+can\s+you\s+do\b'
            r'|\bwhat\s+(are\s+you\s+working\s+on|is\s+your\s+status|phase\s+are\s+you\s+on)\b'
            r'|\byour\s+(status|progress|roadmap)\b',
            "REXY_STATUS",
            {}
        ),
    ]
    
    # ──────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────

    @classmethod
    def check(cls, message: str) -> Optional[Dict[str, Any]]:
        """
        Main entry point. Check if this message can be routed without Groq.

        Args:
            message: Raw user input (any case, any whitespace)

        Returns:
            intent_data dict if routed (same shape as IntentDetector output)
            None if Groq is needed
        """
        _stats["total_checked"] += 1
        msg_lower = message.lower().strip()

        # ── Layer 1: Exact match ──
        if msg_lower in cls.EXACT_COMMANDS:
            intent = cls.EXACT_COMMANDS[msg_lower]
            _stats["exact_hits"] += 1
            logger.debug(f"GATE EXACT | '{msg_lower}' → {intent}")
            return cls._build_result(intent, args={}, reliability="GATE_EXACT")

        # ── Layer 2: Regex patterns ──
        for pattern, intent, args_template in cls.PATTERNS:
            if re.search(pattern, msg_lower):
                # args_template = None → extract args from the message
                # args_template = {}   → no args needed, return empty
                extracted_args = (
                    cls._extract_args(intent, message)
                    if args_template is None
                    else args_template
                )
                _stats["pattern_hits"] += 1
                logger.debug(
                    f"GATE REGEX | pattern='{pattern[:30]}' → {intent} | args={extracted_args}"
                )
                return cls._build_result(intent, args=extracted_args, reliability="GATE_REGEX")

        # ── Layer 3: LLM needed ──
        _stats["llm_passthrough"] += 1
        logger.debug(f"GATE PASS  | Groq needed for: '{msg_lower[:50]}'")
        return None

    @classmethod
    def stats(cls) -> Dict[str, Any]:
        """
        Return gate efficiency stats.
        Use this to see how much of your traffic the gate is handling.

        Example output:
            {
                "total_checked": 150,
                "exact_hits": 40,
                "pattern_hits": 70,
                "llm_passthrough": 40,
                "gate_efficiency": "73.33%"   ← 73% of calls never touch Groq
            }
        """
        total = _stats["total_checked"]
        if total == 0:
            return {**_stats, "gate_efficiency": "0.00%"}

        saved = _stats["exact_hits"] + _stats["pattern_hits"]
        efficiency = (saved / total) * 100
        return {
            **_stats,
            "gate_efficiency": f"{efficiency:.2f}%",
            "groq_calls_saved": saved,
        }

    @classmethod
    def reset_stats(cls) -> None:
        """Reset counters. Call at midnight or on server restart."""
        for key in _stats:
            _stats[key] = 0

    # ──────────────────────────────────────────────────────────
    # ARGUMENT EXTRACTION
    # Called when args_template is None (meaning the args depend
    # on the message content, not a fixed template).
    # ──────────────────────────────────────────────────────────

    @classmethod
    def _extract_args(cls, intent: str, message: str) -> Dict[str, Any]:
        """
        Extract structured args from the message for a given intent.
        Only called when the pattern matched but args need to be parsed.
        """
        if intent == "WEATHER":
            return cls._extract_weather_args(message)

        if intent == "WEB_SEARCH":
            return cls._extract_search_args(message)

        if intent == "MEMORY":
            return cls._extract_memory_args(message)

        if intent == "FILE_READ":
            return cls._extract_file_args(message)

        if intent == "CALENDAR":
            return cls._extract_calendar_args(message)
        
        if intent == "COMPUTER":
            return cls._extract_computer_args(message)

        return {}

    @staticmethod
    def _extract_weather_args(message: str) -> Dict[str, Any]:
        """
        Extract city from weather messages.
        "weather in Ahmedabad" → {"city": "Ahmedabad"}
        "what's the weather"   → {}  (no city — plugin will use default)
        """
        # Try: "weather in X", "temperature in X", "forecast for X"
        city_match = re.search(
            r'\b(?:weather|temperature|forecast|raining|umbrella|weather\s+like)\s+'
            r'(?:in|at|for|of|near)?\s*([A-Za-z][A-Za-z\s]{1,25}?)(?:\s*[?!.,]|$)',
            message,
            re.IGNORECASE
        )
        if city_match:
            city = city_match.group(1).strip().title()
            # Remove stray words that aren't city names
            city = re.sub(r'\b(today|tomorrow|now|currently|right now)\b', '', city, flags=re.IGNORECASE).strip()
            if city and len(city) >= 2:
                return {"city": city}
        return {}

    @staticmethod
    def _extract_search_args(message: str) -> Dict[str, Any]:
        """
        Extract search query.
        "search for python tutorials" → {"query": "python tutorials"}
        """
        # Strip the trigger word and optional "for"
        query = re.sub(
            r'^\s*(search|look\s*up|google|find\s+info(?:rmation)?(?:\s+about)?|find)\s+(for\s+)?',
            '',
            message,
            flags=re.IGNORECASE
        ).strip()
        return {"query": query} if query else {}

    @staticmethod
    def _extract_memory_args(message: str) -> Dict[str, Any]:
        """
        Extract memory action, topic, and content.
        "remember that my exam is March 20" → {"action": "save", "topic": "exam", "content": "exam is March 20"}
        "forget about my sister"            → {"action": "forget", "topic": "sister"}
        "what do you remember about exams"  → {"action": "recall", "topic": "exams"}
        "show everything you remember"      → {"action": "list"}
        """
        msg_lower = message.lower()

        # ── About me ──
        if re.search(
            r'\b(what do you know|what do you remember|tell me|what have you learned)\b.{0,25}\b(about me|about myself)\b'
            r'|\b(what.?s|whats|what is)\s+my\s+(name|birthday|bday|birth date|age)\b'
            r'|\bdo you know my (name|birthday|bday|birth date)\b',
            message, re.IGNORECASE
        ):
            return {"action": "about_me"}
        
        # ── Save ──
        save_match = re.search(
            r'(?:remember\s+that|remind\s+me\s+(?:to|that|about)?)\s+(.+)',
            message, re.IGNORECASE
        )
        if save_match:
            content = save_match.group(1).strip()
            # Try to extract topic (first noun-ish word)
            topic_match = re.search(r'\b(\w+)\b', content)
            topic = topic_match.group(1) if topic_match else None
            return {"action": "save", "content": content, "topic": topic}

        # ── Forget ──
        forget_match = re.search(r'forget\s+about\s+(.+)', message, re.IGNORECASE)
        if forget_match:
            return {"action": "forget", "topic": forget_match.group(1).strip()}

        # ── Recall ──
        recall_match = re.search(
            r'(?:what\s+do\s+you\s+remember|what\s+did\s+i\s+tell\s+you)\s+about\s+(.+)',
            message, re.IGNORECASE
        )
        if recall_match:
            return {"action": "recall", "topic": recall_match.group(1).strip()}

        # ── List all ──
        if re.search(r'(show|list|what)\s+(everything|all)?\s*(you\s+)?remember', msg_lower):
            return {"action": "list"}

        return {}

    @staticmethod
    def _extract_file_args(message: str) -> Dict[str, Any]:
        """
        Extract filename from file read messages.
        "read notes.txt" → {"filename": "notes.txt"}
        """
        file_match = re.search(
            r'\b\w+\.(txt|pdf|py|js|ts|md|csv|json|yaml|yml|html|css|log)\b',
            message, re.IGNORECASE
        )
        if file_match:
            return {"filename": file_match.group(0)}

        # Named file without extension: "read the file called homework"
        named_match = re.search(r'(?:called|named|file)\s+["\']?(\w[\w\s\-]{0,30})["\']?', message, re.IGNORECASE)
        if named_match:
            return {"filename": named_match.group(1).strip()}
        
        return {}
        
    @staticmethod
    def _extract_calendar_args(message: str) -> dict:
        msg_lower = message.lower()

        # ── BOTH ────────────────────────────────────────────────
        if (re.search(r'\b(remember|remind\s+me).{1,60}(add|calendar|schedule)\b', msg_lower) or
            re.search(r'\b(add|schedule).{1,60}(remember|memory|remind)\b', msg_lower) or
            re.search(r'\badd\s+to\s+both\b', msg_lower)):
            topic_match = re.search(
                r'\b(?:remember|remind\s+me\s+(?:that|to|about)?)\s+(?:my\s+)?(\w+)',
                msg_lower
            )
            topic = topic_match.group(1) if topic_match else "event"
            return {"action": "both", "content": message, "topic": topic}

        # ── VIEW ─────────────────────────────────────────────────
        if re.search(r'\b(what.?s\s+on|show|check|view|what\s+do\s+i\s+have|my\s+events)\b', msg_lower):
            window = "today"
            if "tomorrow" in msg_lower:
                window = "tomorrow"
            elif "week" in msg_lower:
                window = "week"
            return {"action": "view", "window": window}

        # ── DELETE ───────────────────────────────────────────────
        if re.search(r'\b(cancel|delete|remove)\b', msg_lower):
            title_match = re.search(
                r'\b(?:cancel|delete|remove)\s+(?:my\s+|the\s+|an?\s+)?(.+?)(?:\s+on\s+.+)?$',
                message, re.IGNORECASE
            )
            title = title_match.group(1).strip() if title_match else None
            return {"action": "delete", "title": title}

        # ── ADD (default) ────────────────────────────────────────
        date_match = re.search(
            r'(?:on\s+|at\s+|for\s+)?'
            r'((?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
            r'january|february|march|april|may|june|july|august|september|october|november|december)'
            r'[\w\s,]*(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)',
            msg_lower
        )
        date_str = date_match.group(1).strip() if date_match else None
        return {"action": "add", "date": date_str}
    
    @staticmethod
    def _extract_computer_args(message: str) -> dict:
        msg = message.lower().strip()

        # Open app
        open_match = re.search(r'\b(open|launch|start|run)\s+(.+?)(?:\s*$)', msg)
        if open_match:
            return {"command": {"action": "open_app", "app": open_match.group(2).strip()}}

        # Set volume
        vol_match = re.search(r'\bvolume\s+(?:to\s+)?(\d+)', msg)
        if vol_match:
            return {"command": {"action": "set_volume", "level": int(vol_match.group(1))}}

        if "volume up" in msg:
            return {"command": {"action": "set_volume", "level": "__up__"}}
        if "volume down" in msg:
            return {"command": {"action": "set_volume", "level": "__down__"}}
        if re.search(r'\bmute\b', msg):
            return {"command": {"action": "set_volume", "level": 0}}
        if re.search(r'\b(what.?s|check|get)\s+(the\s+)?volume\b', msg):
            return {"command": {"action": "get_volume"}}

        # Set brightness
        bright_match = re.search(r'\bbrightness\s+(?:to\s+)?(\d+)', msg)
        if bright_match:
            return {"command": {"action": "set_brightness", "level": int(bright_match.group(1))}}
        if "brightness up" in msg:
            return {"command": {"action": "set_brightness", "level": "__up__"}}
        if "brightness down" in msg:
            return {"command": {"action": "set_brightness", "level": "__down__"}}
        if re.search(r'\b(what.?s|check|get)\s+(the\s+)?brightness\b', msg):
            return {"command": {"action": "get_brightness"}}

        # Screenshot
        if re.search(r'\bscreenshot\b|\bscreen\s+capture\b', msg):
            name_match = re.search(r'\b(?:called|named)\s+(\w[\w\s\-]{0,20})', msg)
            filename = name_match.group(1).strip() if name_match else ""
            return {"command": {"action": "screenshot", "filename": filename}}

        return {}

    # ──────────────────────────────────────────────────────────
    # INTERNAL BUILDER
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_result(intent: str, args: Dict[str, Any], reliability: str) -> Dict[str, Any]:
        """
        Build a complete intent_data dict — same shape as IntentDetector output
        so the rest of the pipeline doesn't need to know where it came from.
        """
        return {
            "intent":      intent,
            "emotion":     "neutral",
            "confidence":  0.99,
            "reliability": reliability,
            "args":        args,
        }