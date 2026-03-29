"""
REXY ORCHESTRATOR v4.0 - CLEAN REWRITE
Architecture: THINK → VERIFY → EXECUTE
Every user message flows through this exact pipeline, no exceptions.

Author: Aman (EEE @ Ahmedabad University)
"""

# ─────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────
from email import message
import asyncio, json, logging, os, re, sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
from dotenv import load_dotenv
import groq_client
import voice_pipeline 
import memory_logger
import pattern_detector
import reflection_engine
import nudge_engine
import morning_briefing
import supabase_db

import uvicorn
import firebase_auth
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from config import validate as validate_config

from observer import emit
from modules.calculator import CalculatorHandler
from modules.chat_intent import ChatHandler
from modules.react_engine import ReActEngine
from rate_limiter import RateLimiter
from modules.plugin_manager import PluginManager
from modules.smart_gate import SmartGate
import io


# ─────────────────────────────────────────────
# WINDOWS UTF-8 FIX (keeps terminal from crying)
# ─────────────────────────────────────────────
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')
if isinstance(sys.stderr, io.TextIOWrapper):
    sys.stderr.reconfigure(encoding='utf-8')

# Initialize pygame audio mixer for TTS playback

# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("rexy.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("rexy.orchestrator")

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
from config import (
    CONFIDENCE_THRESHOLD,
    HIGH_RISK_THRESHOLD,
    CHAT_HISTORY_LIMIT,
    EMOTION_HISTORY_LIMIT,
    RATE_LIMIT_PER_MINUTE,
)

# Valid intents Rexy understands
VALID_INTENTS = {
    "CHAT", "EMOTION_SUPPORT", "CALCULATOR",
    "GET_TIME", "LIST_FILES", "GREET",
    "RESET", "ADVISOR", "MUSIC",
    "WEATHER", "COMPUTER",
}

# Risk classification for each intent
INTENT_RISK = {
    "CHAT":           "low",
    "GREET":          "low",
    "EMOTION_SUPPORT":"low",
    "CALCULATOR":     "low",
    "GET_TIME":       "low",
    "ADVISOR":        "low",
    "MUSIC":          "low",
    "RESET":          "low",     # Always ALLOW — no confirmation
    "LIST_FILES":     "medium",
    "WEATHER": "low",
    "COMPUTER": "low",   # plugin
}

# =============================================================================
# 🧠 GLOBAL STATE
# Central nervous system of Rexy. Do not mutate from outside orchestrator.
# =============================================================================
# ── Per-user sessions — one STATE per connected uid ──
SESSIONS: Dict[str, Any] = {}

def create_session(uid: str) -> Dict[str, Any]:
    """
    Create a fresh state dict for a user.
    Called when a user connects for the first time in this server run.
    """
    return {
        "uid":     uid,
        "turn_id": 0,

        "intent": {
            "mode":        "chat",
            "last_result": None,
            "last_intent": None
        },

        "memory": {
            "emotions":     [],
            "chat_history": [],
            "context_lock": None
        },

        "identity": {
            "name":                 None,
            "preferred_address":    None,
            "response_style":       None,
            "challenge_preference": None
        },

        "device": {
            "mode":         "active",   # active | idle | dozing
            "type":         "desktop",  # desktop | mirror
            "user_present": True,
        },

        "pending":      None,
        "chat_handler": None
    }

def get_session(uid: str) -> Dict[str, Any]:
    """
    Get existing session or create a new one for this uid.
    Loads identity from Supabase on first access.
    """
    if uid not in SESSIONS:
        SESSIONS[uid] = create_session(uid)
        # Load identity from Supabase if available
        user_data = supabase_db.get_user_data(uid)
        if user_data and user_data.get("identity"):
            SESSIONS[uid]["identity"].update(user_data["identity"])
            logger.info(f"Identity loaded from Supabase for uid: {uid}")
    return SESSIONS[uid]

# =============================================================================
# 💾 IDENTITY MEMORY
# Persists across sessions in identity.json. Low-write: only saves on changes.
# =============================================================================
IDENTITY_FILE = "identity.json"

def load_identity() -> None:
    """
    Load identity from disk into a temporary global on startup.
    Only used as fallback when Supabase is unavailable.
    """
    try:
        if os.path.exists(IDENTITY_FILE):
            with open(IDENTITY_FILE, 'r') as f:
                data = json.load(f)
            logger.info("Identity loaded from disk (fallback).")
    except Exception as e:
        logger.warning(f"Identity load failed: {e}")

def save_identity(uid: str, state: Dict[str, Any]) -> None:
    """Save identity to Supabase for this user."""
    try:
        supabase_db.save_identity(uid, state["identity"])
    except Exception as e:
        logger.warning(f"Identity save failed for uid '{uid}': {e}")

def update_identity(uid: str, state: Dict[str, Any], **kwargs) -> None:
    """
    Update identity fields for a specific user.
    Saves to Supabase only if something changed.
    """
    updated = False
    for key, value in kwargs.items():
        if key in state["identity"] and value is not None:
            state["identity"][key] = value
            updated = True
    if updated:
        save_identity(uid, state)

def get_name(state: Dict[str, Any]) -> Optional[str]:
    """Read name from this user's state."""
    return state["identity"].get("name")

# =============================================================================
# 🔊 TTS — NON-BLOCKING TEXT-TO-SPEECH
# Runs in a daemon thread so it never blocks the async pipeline.
# =============================================================================
# NOT NOW

# =============================================================================
# 🧠 THINK — INTENT DETECTOR
# Step 1 of the pipeline. Figures out WHAT the user wants.
# Pre-checks run BEFORE calling Ollama to save time and tokens.
# =============================================================================
class IntentDetector:
    """
    Detects user intent using two-layer approach:
    Layer 1: Fast deterministic pre-checks (regex, no LLM needed)
    Layer 2: Ollama LLM for everything else
    """

    SYSTEM_PROMPT = """You are Rexy's intent classifier. Respond ONLY with valid JSON, nothing else.

Format (exact):
{
  "intent": "ONE_OF_THE_VALID_INTENTS",
  "emotion": "happy|sad|anxious|neutral|thinking|bored|excited",
  "confidence": 0.95,
  "args": {}
}

The "args" field contains structured arguments extracted from the message.

- WEATHER    → {"city": "city name"}
              e.g. "do I need an umbrella in Tokyo?" → {"city": "Tokyo"}
              e.g. "weather" (no city mentioned) → {}

- WEB_SEARCH → {"query": "search query"}
              e.g. "search latest AI news" → {"query": "latest AI news"}

- FILE_READ  → {"filename": "filename if mentioned"}
              e.g. "read notes.txt" → {"filename": "notes.txt"}
              e.g. "show inbox files" → {}

- MEMORY     → {"action": "save|recall|forget|list", "topic": "topic if any", "content": "content if saving"}
              e.g. "remember my exam is March 20" → {"action": "save", "topic": "exam", "content": "exam is March 20"}
              e.g. "what do you remember about my sister" → {"action": "recall", "topic": "sister"}
              e.g. "forget about my exam" → {"action": "forget", "topic": "exam"}
              e.g. "show everything you remember" → {"action": "list"}

- All other intents → {}

If you cannot extract a clean argument, leave args as {}.
Never guess — empty is safer than wrong.

Valid intents (check in this STRICT priority order):

1. CALCULATOR
   → ONLY if message contains math digits with + - * / operators
   → OR message contains the words "calc" or "calculate"
   → Examples: "10+5", "calc 50*3", "calculate 100/4", "what is 8 times 9"
   → NOT for: "memory usage", "storage usage", "how much RAM"

2. GET_TIME
   → ONLY if message explicitly asks for the current time or clock
   → Examples: "what time is it", "current time", "tell me the time"
   → NOT for: history questions, general knowledge, anything with "when was"

3. LIST_FILES
   → ONLY if message asks to list or show directory/folder contents
   → Examples: "list my files", "show files", "what's in the folder"
   → NOT for: reading a specific file (that's FILE_READ)

4. RESET
   → ONLY if message asks to reset, clear, or start over
   → Examples: "reset", "clear everything", "start fresh", "forget everything and restart"

5. MUSIC
   → ONLY if message asks to play music, songs, or a playlist
   → Examples: "play some music", "chill songs", "put on a playlist", "play something"

6. WEATHER
   → ONLY if message asks about current weather, temperature, rain, forecast, or climate for any city
   → Examples: "weather in Ahmedabad", "is it raining in Delhi", "what's the temperature in London", "how's the weather today", "what's it like outside in Tokyo"
   → NOT for: historical climate facts, general geography questions

7. WEB_SEARCH
   → ONLY if message explicitly asks to search, look up, google, or find something online
   → Examples: "search for python tutorials", "look up Nikola Tesla", "google latest AI news", "find information about black holes"
   → NOT for: general knowledge questions Rexy can answer herself (those are CHAT)

8. MEMORY
   → ONLY if message uses explicit memory phrases like "remember that", "remind me", "don't forget", "what did I tell you about", "what do you remember", "forget about X"
   → Examples: "remember that my exam is March 20", "what do you remember about my sister", "forget about my exam"
   → NOT for: RAM, hardware memory, storage, system stats (those are SYSTEM_INFO)
   → NOT for: "my name is X" (that is CHAT)

9. FILE_READ
   → ONLY if message asks to read, open, load, or show a specific file, OR list inbox files
   → Examples: "read notes.txt", "open my resume", "what's in report.pdf", "show me inbox files", "read the file called homework"
   → NOT for: listing system files (that is LIST_FILES)

10. SYSTEM_INFO
    → ONLY if message asks about hardware performance or system statistics
    → Examples: "cpu usage", "ram usage", "check battery", "disk space", "storage usage", "how much memory is my laptop using", "system info", "how long has my pc been on", "what is my processor speed"
    → Keywords: CPU, RAM, battery, disk, storage, memory usage, uptime, processor, system stats

11. EMOTION_SUPPORT
    → ONLY if user explicitly expresses emotional distress or negative feelings
    → Examples: "i'm feeling sad", "i'm really anxious about my exams", "i feel so overwhelmed", "i'm stressed out", "i've been crying"
    → NOT for: boredom (that is ADVISOR)

12. ADVISOR
    → ONLY if user explicitly says they are bored or has nothing to do and wants suggestions
    → Examples: "i'm so bored", "i have nothing to do", "suggest something fun", "what should i do right now"

13. GREET
    → ONLY if message is purely a greeting with no other request
    → Examples: "hello", "hi rexy", "hey", "good morning", "what's up", "yo"
    → NOT for: greetings combined with a question (those go to CHAT or relevant intent)

14. CHAT
    → DEFAULT for absolutely everything else
    → General knowledge, opinions, explanations, facts, coding help, advice, creative writing
    → When in doubt → CHAT. CHAT is always the safe fallback.

STRICT RULES:
- Output ONE intent only
- No explanation, no markdown, pure JSON
- Never output an intent not listed above
- When two intents seem possible, pick the higher-numbered one as tiebreaker (more specific wins)
- SYSTEM_INFO always beats MEMORY when the topic is hardware/RAM/storage
- WEATHER always beats WEB_SEARCH when the topic is weather"""


    @staticmethod
    def detect(message: str, history: list) -> dict:
        """
        THINK stage — two-layer intent detection.
 
        Layer 0: SmartGate  — deterministic, no LLM, ~0ms
        Layer 1: Groq LLM   — only fires when Layer 0 returns None
 
        Returns standard intent_data dict:
        {
            "intent":      str,
            "emotion":     str,
            "confidence":  float,
            "reliability": str,   # "GATE_EXACT" | "GATE_REGEX" | "HIGH" | "LOW" | ...
            "args":        dict
        }
        """
        # ── LAYER 0: SmartGate ──────────────────────────────────
        # Check deterministic patterns before spending a Groq token.
        # For ~70% of messages, this is all we need.
        gate_result = SmartGate.check(message)
        if gate_result is not None:
            logger.info(
                f"GATE HIT | intent={gate_result['intent']} | "
                f"reliability={gate_result['reliability']} | "
                f"groq_saved=True"
            )
            emit("GATE_HIT", {
                "intent":      gate_result["intent"],
                "reliability": gate_result["reliability"],
                "args":        gate_result["args"],
            })
            return gate_result
 
        # ── LAYER 1: Groq LLM ──────────────────────────────────
        # Gate didn't recognise it — this message needs reasoning.
        # Log the call so we can track Groq usage over time.
        logger.info("GATE MISS | calling Groq...")
        emit("LLM_CALL", {"reason": "gate_miss", "message_len": len(message)})
 
        try:
            recent_history = history[-2:] if history else []
            raw = groq_client.chat(
                messages=[
                    {"role": "system",  "content": IntentDetector.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Message: '{message}'\n"
                            f"Recent history: {json.dumps(recent_history) if recent_history else 'none'}"
                        )
                    }
                ],
                temperature=0.1
            )
            if raw is None:
                raise Exception("Groq returned None")
 
            # Strip markdown fences if present
            raw = re.sub(r'```(?:json)?', '', raw).strip()
            result = json.loads(raw)
 
            intent = result.get("intent", "CHAT").upper()
            if intent not in VALID_INTENTS:
                logger.warning(f"LLM returned unknown intent '{intent}', falling back to CHAT")
                return {
                    "intent":      "CHAT",
                    "emotion":     "neutral",
                    "confidence":  0.3,
                    "reliability": "MALFORMED_INTENT",
                    "args":        {}
                }
 
            emotion    = result.get("emotion", "neutral")
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            reliability = "HIGH" if confidence >= CONFIDENCE_THRESHOLD else "LOW"
            args       = result.get("args", {})
            if not isinstance(args, dict):
                args = {}
 
            return {
                "intent":      intent,
                "emotion":     emotion,
                "confidence":  confidence,
                "reliability": reliability,
                "args":        args
            }
 
        except json.JSONDecodeError as e:
            logger.warning(f"IntentDetector JSON parse error: {e}")
            return {"intent": "CHAT", "emotion": "neutral", "confidence": 0.2, "reliability": "JSON_ERROR", "args": {}}
 
        except Exception as e:
            logger.warning(f"IntentDetector Groq error: {e}")
            return {"intent": "CHAT", "emotion": "neutral", "confidence": 0.1, "reliability": f"EXCEPTION:{str(e)[:30]}", "args": {}}

# =============================================================================
# 🔍 VERIFY — SAFETY VERIFIER
# Step 2. Decides if the detected intent should be ALLOWED, CLARIFIED, or REJECTED.
# CLARIFY = ask user to rephrase (NOT a yes/no confirmation prompt).
# =============================================================================
class SafetyVerifier:
    """
    Verifies intent before execution.

    Decision rules:
    - CHAT, GREET → always ALLOW (never blocked, never clarified)
    - RESET        → always ALLOW
    - Low risk + confidence >= 0.75 → ALLOW
    - Medium risk + confidence >= 0.75 → ALLOW
    - Any intent + confidence < 0.75 → CLARIFY (ask to rephrase)
    - High risk + confidence < 0.90 → REJECT
    """

    @staticmethod
    def verify(intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes intent_data from IntentDetector.
        Returns a verification dict: {"decision", "reason"}
        Possible decisions: "ALLOW", "CLARIFY", "REJECT"
        """
        intent = intent_data["intent"]
        confidence = intent_data["confidence"]
        reliability = intent_data.get("reliability", "HIGH")

        # ── Rule 0: Gate results are always trusted ──────────────
        # GATE_EXACT and GATE_REGEX are deterministic — no LLM uncertainty
        if reliability in ("GATE_EXACT", "GATE_REGEX"):
            return {"decision": "ALLOW", "reason": f"Gate-matched intent always allowed: {intent}"}
        
        # ── Rule 1: CHAT and GREET are ALWAYS allowed ──
        # These are safe, conversational. Never block them.
        if intent in ("CHAT", "GREET"):
            return {"decision": "ALLOW", "reason": f"Conversational intent always allowed: {intent}"}

        # ── Rule 2: RESET is always allowed ──
        if intent == "RESET":
            return {"decision": "ALLOW", "reason": "RESET always allowed, no confirmation needed"}

        # ── Rule 3: Low reliability from LLM → ask user to rephrase ──
        if reliability != "HIGH":
            return {
                "decision": "CLARIFY",
                "reason": f"Low confidence ({confidence:.2f}) for {intent}. Ask user to rephrase."
            }

        # ── Rule 4: Confident enough → allow ──
        risk = INTENT_RISK.get(intent, "high")

        if risk in ("low", "medium") and confidence >= CONFIDENCE_THRESHOLD:
            return {"decision": "ALLOW", "reason": f"Confidence OK ({confidence:.2f}) for {risk}-risk intent {intent}"}

        # ── Rule 5: High risk without high confidence → reject ──
        if risk == "high" and confidence < HIGH_RISK_THRESHOLD:
            return {"decision": "REJECT", "reason": f"High-risk intent {intent} rejected (confidence {confidence:.2f} < {HIGH_RISK_THRESHOLD})"}

        # ── Default: clarify if we're unsure ──
        return {"decision": "CLARIFY", "reason": f"Unable to verify {intent} safely, asking user to rephrase"}

# =============================================================================
# 🚀 EXECUTE — EXECUTION ENGINE
# Step 3. Routes intent to the correct handler.
# IMPORTANT: Only uses `intent ==` checks. NO keyword matching here.
# Keyword matching already happened in THINK. Don't duplicate it here.
# =============================================================================
class ExecutionEngine:
    """
    Routes a verified intent to the correct handler module.
    Priority order:
    RESET → GET_TIME → LIST_FILES → CALCULATOR → ADVISOR → MUSIC → CHAT/GREET/EMOTION_SUPPORT
    """

    @staticmethod
    def execute(intent: str, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Execute the appropriate handler for the given intent.
        Returns: {"reply": str, "emotion": str, "state": str}
        """
        try:
            # ── PRIORITY 1: RESET ──
            # Clears session state. Always works, no fuss.
            if intent == "RESET":
                state["intent"]["mode"]        = "chat"
                state["intent"]["last_result"] = None
                state["intent"]["last_intent"] = None
                state["memory"]["context_lock"] = None
                state["pending"]               = None
                state["chat_handler"]          = None
                return {
                    "reply": "🔄 Done! Fresh start — what's on your mind? 😊",
                    "emotion": "happy",
                    "state": "speaking"
                }

            # ── PRIORITY 2: GET_TIME ──
            if intent == "GET_TIME":
                from zoneinfo import ZoneInfo
                current_time = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%I:%M %p")
                return {
                    "reply": f"🕐 It's {current_time} right now!",
                    "emotion": "neutral",
                    "state": "speaking"
                }

            # ── PRIORITY 3: LIST_FILES ──
            if intent == "LIST_FILES":
                try:
                    files = os.listdir('rexy_inbox')
                    visible = files[:10]
                    file_list = ', '.join(visible)
                    overflow  = f" (+{len(files) - 10} more)" if len(files) > 10 else ""
                    return {
                        "reply": f"📁 Files here: {file_list}{overflow}",
                        "emotion": "neutral",
                        "state": "speaking"
                    }
                except Exception as e:
                    return {
                        "reply": f"❌ Couldn't read files: {str(e)[:60]}",
                        "emotion": "neutral",
                        "state": "speaking"
                    }

            # ── PRIORITY 4: CALCULATOR ──
            if intent == "CALCULATOR":
                # Set mode so follow-up expressions chain correctly
                state["intent"]["mode"] = "calculator"

                # Import here to avoid circular imports at module level
                calc = CalculatorHandler()
                result = calc.process(message, state)

                # Sync state changes from calculator back to global state
                state["intent"]["mode"]        = result.get("mode", "calculator")
                state["intent"]["last_result"] = result.get("last_result")

                return {
                    "reply": result["reply"],
                    "emotion": "thinking",
                    "state": result.get("state", "thinking")
                }

            # ── PRIORITY 5: ADVISOR ──
            if intent == "ADVISOR":
                state["intent"]["mode"] = "chat"
                return {
                    "reply": (
                        "😴 Boredom? I've got options:\n"
                        "• 🧮 Quick math challenge\n"
                        "• 🎵 Tell me to play some music\n"
                        "• 💬 Tell me something — I'll surprise you\n"
                        "• 🤔 Ask me anything\n\n"
                        "What sounds good?"
                    ),
                    "emotion": "neutral",
                    "state": "speaking"
                }

            # ── PRIORITY 6: MUSIC ──
            if intent == "MUSIC":
                state["intent"]["mode"] = "chat"
                return {
                    "reply": "🎵 Music mode! What's the vibe?\n• Chill\n• Focus\n• Hype\nJust say the word.",
                    "emotion": "happy",
                    "state": "speaking"
                }

            # ── PRIORITY 7: CHAT / GREET / EMOTION_SUPPORT ──
            if intent in ("CHAT", "GREET", "EMOTION_SUPPORT"):
                state["intent"]["mode"]         = "chat"
                state["intent"]["last_result"]  = None
                state["memory"]["context_lock"] = "chat"

                # Lazy-load the ChatHandler (only created once per session)
                if state["chat_handler"] is None:
                    state["chat_handler"] = ChatHandler()

                # Name detection — runs BEFORE LLM to avoid wasting a call
                name_match = re.search(
                    r'\b(my name is|call me)\s+([A-Za-z][A-Za-z\s]{0,30})(?=\s|$|[.!?])',
                    message,
                    re.IGNORECASE
                )
                if name_match:
                    detected_name = name_match.group(2).strip().title()
                    state["pending"] = {
                        "status":      "awaiting_name_confirm",
                        "name":        detected_name,
                        "retry_count": 0,
                        "max_retries": 3
                    }
                    return {
                        "reply": f"Should I remember your name as '{detected_name}'? (yes / no)",
                        "emotion": "neutral",
                        "state": "speaking"
                    }

                # Sparingly use name on greetings and genuine encouragement
                name = get_name(state)
                message_lower = message.lower()

                # Shorten replies if user is in idle/mirror mode
                if state.get("device", {}).get("mode") == "idle":
                    message = message + " (keep your reply brief, one or two sentences max)"

                # Generate response via ChatHandler
                reply = state["chat_handler"].generate_response(message, emotion, intent)

                if name:
                    is_greeting = any(w in message_lower for w in ["hello", "hi", "hey", "good morning", "good evening"])
                    if is_greeting:
                        reply = f"Hey {name}! {reply}"

                return {
                    "reply": reply,
                    "emotion": emotion,
                    "state": "speaking"
                }

            # ── REXY STATUS ──
            if intent == "REXY_STATUS":
                import self_awareness
                reply = self_awareness.get_reply(message)
                return {
                    "reply": reply,
                    "emotion": "happy",
                    "state": "speaking"
                }
            
            # ── FALLBACK (shouldn't reach here normally) ──
            if PLUGIN_MANAGER.has(intent):
                return PLUGIN_MANAGER.execute(intent, message, emotion, state, args)

            logger.warning(f"ExecutionEngine received unknown intent: {intent}")
            return {
                "reply": "🤔 I'm not sure what you mean. Try: calc 10+5, time, weather in Ahmedabad, or just chat!",
                "emotion": "neutral",
                "state": "speaking"
            }
        
        except Exception as e:
            logger.error(f"ExecutionEngine crash | intent={intent} | message='{message[:50]}' | error={e}")
            return {
                "reply": "Something went wrong on my end. Try again?",
                "emotion": "neutral",
                "state": "speaking"
            }
# =============================================================================
# 🎯 PENDING STATE MACHINE
# Handles flows that span multiple turns (name confirm, etc.)
# =============================================================================
async def handle_pending(message: str, pending: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Process a message when there's an active pending state.
    Returns a result dict if the pending state handled the message, else None.
    """
    message_lower = message.lower().strip()
    status = pending.get("status")

    # ── Name confirmation flow ──
    if status == "awaiting_name_confirm":
        if any(w in message_lower for w in ["yes", "yeah", "yep", "confirm", "ok", "sure"]):
            update_identity(state["uid"], state, name=pending["name"])
            state["pending"] = None
            return {
                "reply": f"✅ Got it! I'll remember you as {pending['name']}. 😊",
                "emotion": "happy",
                "state": "speaking"
            }
        elif any(w in message_lower for w in ["no", "nope", "cancel", "nah"]):
            state["pending"] = None
            return {"reply": "No problem! 😊", "emotion": "neutral", "state": "speaking"}
        else:
            # Retry
            pending["retry_count"] += 1
            if pending["retry_count"] >= pending["max_retries"]:
                state["pending"] = None
                return {
                    "reply": "No worries, skipping that for now.",
                    "emotion": "neutral",
                    "state": "speaking"
                }
            return {
                "reply": f"Just say yes or no — should I call you {pending['name']}?",
                "emotion": "neutral",
                "state": "speaking"
            }

    # Unknown pending status — clear it and continue normally
    logger.warning(f"Unknown pending status '{status}', clearing.")
    state["pending"] = None
    return None

# =============================================================================
# 🎯 MAIN PIPELINE: process_message
# THINK → VERIFY → EXECUTE, every single time.
# =============================================================================
async def process_message(message: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    The full THINK → VERIFY → EXECUTE pipeline.
    This is the only path a message should travel through.
    Returns: {"reply", "emotion", "state"}
    """

    try:
        state["turn_id"] += 1
        logger.info(f"TURN {state['turn_id']} | '{message[:60]}'")

        # ── STEP 0: Check active pending state first ──
        # If we're waiting for a name confirmation etc., handle that before anything else.
        if state.get("pending"):
            pending_result = await handle_pending(message, state["pending"], state)
            if pending_result:
                return pending_result
            # If pending returned None, the pending state was cleared — continue normally

        # ── STEP 0.5: CALCULATOR CHAIN MODE PRE-CHECK ──
        # If we're already in calculator mode, intercept before hitting Ollama.
        # Handles: "*10", "times 3", "divide by 2", "+ 50" etc.
        if state["intent"].get("mode") == "calculator":
            chain_triggers = re.search(
                r'(\b(times|multiply|divide|plus|minus|add|subtract)\b|^[\+\-\*\/]\s*\d)',
                message.lower().strip()
            )
            pure_op = re.match(r'^[\+\-\*\/]\s*\d', message.strip())
            
            if chain_triggers or pure_op:
                from modules.calculator import CalculatorHandler
                calc   = CalculatorHandler()
                result = calc.process(message, state)
                state["intent"]["mode"]        = result.get("mode", "calculator")
                state["intent"]["last_result"] = result.get("last_result")
                return {
                    "reply":   result["reply"],
                    "emotion": "thinking",
                    "state":   result.get("state", "thinking")
                }
            
        # ── STEP 1: THINK — detect intent ──
        intent_data = IntentDetector.detect(message, state["memory"]["chat_history"])
        logger.info(
            f"THINK | intent={intent_data['intent']} | "
            f"confidence={intent_data['confidence']:.2f} | "
            f"reliability={intent_data['reliability']}"
        )
        emit("INTENT_LOCKED", {
            "intent":      intent_data["intent"],
            "confidence":  intent_data["confidence"],
            "reliability": intent_data["reliability"],
            "turn":        state["turn_id"]
        })

        # ── STEP 2: VERIFY — safety check ──
        verification = SafetyVerifier.verify(intent_data)
        logger.info(f"VERIFY | decision={verification['decision']} | reason={verification['reason']}")
        emit("SAFETY_CHECK", {
            "decision": verification["decision"],
            "reason":   verification["reason"],
            "turn":     state["turn_id"]
        })

        # ── Handle CLARIFY (ask user to rephrase, not yes/no) ──
        if verification["decision"] == "CLARIFY":
            emit("DECISION_NOTE", {"decision": "CLARIFY", "intent": intent_data["intent"]})
            return {
                "reply": (
                    "I'm not quite sure what you meant. "
                    "Could you rephrase that? "
                    "(e.g. say 'calc 10+5' for math, 'what time is it', or just chat!)"
                ),
                "emotion": "neutral",
                "state": "speaking",
                "intent": "CHAT"   # ← add to early returns
            }

        # ── Handle REJECT ──
        if verification["decision"] == "REJECT":
            emit("DECISION_NOTE", {"decision": "REJECT", "intent": intent_data["intent"]})
            return {
                "reply": "🔒 That doesn't seem safe to do right now. Try something else?",
                "emotion": "neutral",
                "state": "speaking"
            }

        # ── STEP 3: EXECUTE ──
        result = ExecutionEngine.execute(
            intent_data["intent"],
            message,
            intent_data["emotion"],
            state,
            intent_data.get("args", {})
        )
        # ── STEP 3.5: ReAct — interpret if advice question ──
        if ReActEngine.needs_react(message, intent_data["intent"]):
            logger.info(f"ReAct | TRIGGERED | intent={intent_data['intent']}")
            result = ReActEngine.run(message, intent_data["intent"], result)

        # ── STEP 3.6: Shape response — smooth robotic output ──
        result["reply"] = voice_pipeline.shape_response(result["reply"])

        logger.info(f"EXECUTE | {intent_data['intent']} → '{result['reply'][:60]}'")

        emit("EXECUTION_RESULT", {
            "intent": intent_data["intent"],
            "reply":  result["reply"][:80],
            "turn":   state["turn_id"]
        })

        # ── STEP 4: Update memory (single write after execution) ──
        # Track emotion history
        state["memory"]["emotions"].append({
            "type":   result["emotion"],
            "turn":   state["turn_id"],
            "intent": intent_data["intent"]
        })
        state["memory"]["emotions"] = state["memory"]["emotions"][-EMOTION_HISTORY_LIMIT:]

        # Append to chat history for context on next turn
        state["memory"]["chat_history"].extend([
            {"role": "user",      "content": message},
            {"role": "assistant", "content": result["reply"]}
        ])
        state["memory"]["chat_history"] = state["memory"]["chat_history"][-CHAT_HISTORY_LIMIT:]

        state["intent"]["last_intent"] = intent_data["intent"]

        # ── STEP 5: Log interaction for pattern detection ──
        memory_logger.log_interaction(
            uid=state["uid"],
            intent=intent_data["intent"],
            turn_count=state["turn_id"],
        )

        # ── STEP 6: Reflection — weave pattern observation if conditions match ──
        patterns = pattern_detector.get_patterns(state["uid"])
        result["reply"] = reflection_engine.maybe_reflect(
            uid=state["uid"],
            reply=result["reply"],
            intent=intent_data["intent"],
            patterns=patterns,
        )
        
        return {
            "reply":   result["reply"],
            "emotion": result["emotion"],
            "state":   result.get("state", "speaking")
        }

    except Exception as e:
        logger.critical(f"PIPELINE CRASH: {e}", exc_info=True)
        return _safe_fallback(message, state)
    
def _safe_fallback(message: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Last-resort fallback. Clears any dangerous pending state.
    Rexy should NEVER crash — she just lands here instead.
    """
    state["pending"] = None
    logger.critical(f"SAFETY_FALLBACK triggered | message='{message[:50]}'")
    return {
        "reply": "🔒 Something went wrong on my end. Try: calc, time, files, or just chat!",
        "emotion": "neutral",
        "state": "idle"
    }

async def _nudge_loop(uid: str, websocket: WebSocket, session: dict):
    """Fire nudge check on connect (after 10s), then every 30 minutes."""
    await asyncio.sleep(10)
    while True:
        try:
            last_active = session.get("last_active", 0)
            session_active = (datetime.now().timestamp() - last_active) < 300
            nudge = nudge_engine.evaluate(uid, session_active=session_active)
            if nudge:
                await websocket.send_text(json.dumps({
                    "type":       "nudge",
                    "reply":      nudge["nudge_text"],
                    "nudge_type": nudge["nudge_type"],
                    "emotion":    "happy",
                    "intent":     "NUDGE"
                }))
        except Exception as e:
            logger.warning(f"Nudge loop error: {e}")
            break
        await asyncio.sleep(1800)

async def _send_briefing(websocket: WebSocket, data: dict):
    await asyncio.sleep(2)
    try:
        await websocket.send_text(json.dumps(data))
    except Exception as e:
        logger.warning(f"Briefing send failed: {e}")

# =============================================================================
# 🌐 FASTAPI APPLICATION + WEBSOCKET
# =============================================================================
load_dotenv()
load_identity()
validate_config()
firebase_auth.initialize()
supabase_db.initialize()
groq_client.initialize()  


PLUGIN_MANAGER = PluginManager()
PLUGIN_MANAGER.load_all()
VALID_INTENTS.update(PLUGIN_MANAGER.get_all_intents())
INTENT_RISK.update(PLUGIN_MANAGER.get_risk_levels())

app = FastAPI(title="Rexy AI Assistant", version="4.0")
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/gate-stats")
async def gate_stats():
    """Returns SmartGate efficiency stats. Useful for monitoring."""
    return SmartGate.stats()

@app.get("/")
async def get_index():
    """Serve the frontend HTML if it exists, otherwise show a placeholder."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Rexy v4.0</h1><p>WebSocket: ws://localhost:8000/ws</p>")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket handler.
    On every new connection: reset mode, last_result, and pending state.
    Identity persists — it's loaded from disk.
    """
    await websocket.accept()
    logger.info("WebSocket connected.")

    # ── STEP 6: AUTH CHECK ──
    # First message MUST be {"type": "auth", "token": "..."}
    # If token is missing or invalid → close connection immediately
    try:
        auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth_payload = json.loads(auth_data)

        if auth_payload.get("type") != "auth":
            logger.warning("WebSocket rejected — first message was not auth.")
            await websocket.close(code=1008)
            return

        token = auth_payload.get("token", "").strip()
        decoded = firebase_auth.verify_token(token)

        if decoded is None:
            logger.warning("WebSocket rejected — invalid Firebase token.")
            await websocket.send_text(json.dumps({
                "reply":   "🔒 Authentication failed. Please sign in again.",
                "emotion": "neutral",
                "state":   "speaking",
                "intent":  "CHAT",
                "turn_id": 0
            }))
            await websocket.close(code=1008)
            return

        # Token valid — log who connected
        uid   = decoded.get("uid", "unknown")
        email = decoded.get("email", "unknown")
        logger.info(f"WebSocket authenticated — uid: {uid} email: {email}")

        user_data = supabase_db.get_or_create_user(uid, email)
        logger.info(f"User data loaded — memories: {len(user_data.get('memories', {}))} items")
        session = get_session(uid)

    except asyncio.TimeoutError:
        logger.warning("WebSocket rejected — auth token not received within 10s.")
        await websocket.close(code=1008)
        return
    except Exception as e:
        logger.warning(f"WebSocket auth error: {e}")
        await websocket.close(code=1008)
        return

    # ── AUTH PASSED — normal session setup ──
    session["intent"]["mode"]        = "chat"
    session["intent"]["last_result"] = None
    session["pending"]               = None
    session["chat_handler"]          = None
    asyncio.create_task(_nudge_loop(uid, websocket, session))
    if morning_briefing.should_show(uid):
        briefing_data = morning_briefing.assemble(uid, session)
        if briefing_data:
            morning_briefing.mark_shown(uid)
            asyncio.create_task(_send_briefing(websocket, briefing_data))

    # One rate limiter per connection
    limiter = RateLimiter()
    MAX_MESSAGE_LEN = 1500   

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            message = payload.get("message", "").strip()

            if not message:
                continue

            # ── INPUT SIZE LIMITS ──────────────────────────────────
            # Hard cap: 1500 chars for normal messages.
            # Code analysis cap: 300 lines (~12000 chars) is handled
            # at the plugin level, not here. Here we block giant pastes.
            # chars — tighter than old 1000? No — 1500 is slightly more generous for natural speech
            # If you want tighter, drop to 800. The key insight: a sentence
            # is ~80 chars, so 1500 ≈ ~18 sentences — plenty for any real question.
 
            if len(message) > MAX_MESSAGE_LEN:
                emit("INPUT_REJECTED", {
                    "reason":   "message_too_long",
                    "length":   len(message),
                    "limit":    MAX_MESSAGE_LEN,
                    "uid":      uid,
                })
                await websocket.send_text(json.dumps({
                    "reply":   (
                        f"⚠️ That's a bit long ({len(message)} chars). "
                        f"Keep messages under {MAX_MESSAGE_LEN} characters — "
                        f"break it into smaller pieces if needed!"
                    ),
                    "emotion": "neutral",
                    "state":   "speaking",
                    "intent":  "CHAT",
                    "turn_id": session["turn_id"]
                }))
                continue

            # ── RATE LIMIT CHECK ──
            if not limiter.is_allowed():
                await websocket.send_text(json.dumps({
                    "reply":   f"⏳ Slow down! Max {limiter.limit} messages per minute. "
                               f"Try again in a few seconds.",
                    "emotion": "neutral",
                    "state":   "speaking",
                    "intent":  "CHAT",
                    "turn_id": session["turn_id"]
                }))
                continue

            # ── STATE UPDATE FROM FRONTEND ──
            if payload.get("type") == "state_update":
                new_mode = payload.get("mode")
                if new_mode in ("active", "idle", "dozing"):
                    session["device"]["mode"] = new_mode
                    session["device"]["user_present"] = new_mode == "active"
                    logger.info(f"Device state → mode={new_mode} | uid={uid[:8]}")
                continue

            # ── VOICE PIPELINE: humanize + confidence filter ──
            proceed, message, fallback = voice_pipeline.process_input(message)
            if not proceed:
                await websocket.send_text(json.dumps({
                    "reply":   fallback,
                    "emotion": "neutral",
                    "state":   "speaking",
                    "intent":  "CHAT",
                    "turn_id": session["turn_id"]
                }))
                continue

            logger.info(f"USER: {message}")
            from observer import timed
            with timed("full_pipeline", uid=uid, intent="unknown"):
                session["last_active"] = datetime.now().timestamp()
                result = await process_message(message, session)

            response = {
                "reply":   result["reply"],
                "emotion": result["emotion"],
                "state":   result["state"],
                "intent":  result.get("intent", "CHAT"),
                "turn_id": session["turn_id"],
                "chunks":  voice_pipeline.chunk_response(result["reply"])   
}

            logger.info(f"REXY: {result['reply'][:60]}")
            await websocket.send_text(json.dumps(response))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected — uid: {uid}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)

@app.websocket("/ws-agent")
async def agent_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for rexy_local_agent.py.
    """
    from modules.plugins.computer_plugin import (
        get_agent_queue, _pending_commands, _connected_agents
    )

    await websocket.accept()
    agent_id = id(websocket)
    _connected_agents.add(agent_id)
    logger.info(f"Local agent connected — id: {agent_id}")

    queue = get_agent_queue()

    try:
        async def send_commands():
            while True:
                item = await queue.get()
                await websocket.send_text(json.dumps({
                    "type":    "command",
                    "cmd_id":  item["cmd_id"],
                    "command": item["command"]
                }))

        async def receive_results():
            while True:
                try:
                    raw = await websocket.receive_text()
                    msg = json.loads(raw)
                    if msg.get("type") == "result":
                        cmd_id = msg.get("cmd_id", "")
                        future = _pending_commands.get(cmd_id)
                        if future and not future.done():
                            future.set_result({
                                "success": msg.get("success", False),
                                "message": msg.get("message", ""),
                                "data":    msg.get("data", {})
                            })
                    elif msg.get("type") == "agent_hello":
                        logger.info(f"Agent hello — platform: {msg.get('platform')}")
                except json.JSONDecodeError:
                    pass
                except Exception:
                    break
                
        await asyncio.gather(send_commands(), receive_results())

    except WebSocketDisconnect:
        logger.info(f"Local agent disconnected — id: {agent_id}")
    except Exception as e:
        logger.error(f"Agent WebSocket error: {e}")
    finally:
        _connected_agents.discard(agent_id)


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    print("🚀 Starting Rexy v4.0 — THINK → VERIFY → EXECUTE")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
