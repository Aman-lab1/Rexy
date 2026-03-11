"""
REXY ORCHESTRATOR v4.0 - CLEAN REWRITE
Architecture: THINK → VERIFY → EXECUTE
Every user message flows through this exact pipeline, no exceptions.

Author: Aman (EEE @ Ahmedabad University)
"""

# ─────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────
import asyncio, json, logging, os, re, subprocess, sys, tempfile, threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

import ollama
import pygame
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from observer import emit
from modules.calculator import CalculatorHandler
from modules.chat_intent import ChatHandler
from modules.plugin_manager import PluginManager
import io

# ─────────────────────────────────────────────
# WINDOWS UTF-8 FIX (keeps terminal from crying)
# ─────────────────────────────────────────────
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')
if isinstance(sys.stderr, io.TextIOWrapper):
    sys.stderr.reconfigure(encoding='utf-8')

# Initialize pygame audio mixer for TTS playback
pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)

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
CONFIDENCE_THRESHOLD = 0.75      # Below this → CLARIFY
HIGH_RISK_THRESHOLD  = 0.90      # For risky intents (future use)
CHAT_HISTORY_LIMIT   = 12        # Max turns in session memory
EMOTION_HISTORY_LIMIT = 5        # Max emotions to keep

# Valid intents Rexy understands
VALID_INTENTS = {
    "CHAT", "EMOTION_SUPPORT", "CALCULATOR",
    "GET_TIME", "LIST_FILES", "GREET",
    "RESET", "ADVISOR", "MUSIC",
    "WEATHER" #plugin
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
    "WEATHER": "low",   # plugin
}

# =============================================================================
# 🧠 GLOBAL STATE
# Central nervous system of Rexy. Do not mutate from outside orchestrator.
# =============================================================================
STATE: Dict[str, Any] = {
    "turn_id": 0,

    "intent": {
        "mode": "chat",        # current mode: "chat" | "calculator"
        "last_result": None,   # last calculator result (for chaining)
        "last_intent": None    # what happened on the previous turn
    },

    "memory": {
        "emotions": [],        # last 5 emotions: [{"type", "turn", "intent"}]
        "chat_history": [],    # last 12 messages sent to Ollama
        "context_lock": None   # which module "owns" the context right now
    },

    "identity": {
        "name": None,
        "preferred_address": None,
        "response_style": None,       # "concise" | "verbose" | "adaptive"
        "challenge_preference": None
    },

    "pending": None,          # active pending-state flow (name confirm, etc.)
    "chat_handler": None      # lazy-loaded ChatHandler instance
}

# =============================================================================
# 💾 IDENTITY MEMORY
# Persists across sessions in identity.json. Low-write: only saves on changes.
# =============================================================================
IDENTITY_FILE = "identity.json"

def load_identity() -> None:
    """Load persisted identity from disk into STATE on startup."""
    try:
        if os.path.exists(IDENTITY_FILE):
            with open(IDENTITY_FILE, 'r') as f:
                data = json.load(f)
                STATE["identity"].update(data)
            logger.info("Identity loaded from disk.")
    except Exception as e:
        logger.warning(f"Identity load failed (starting fresh): {e}")

def save_identity() -> None:
    """Write current identity to disk. Called only when something changes."""
    try:
        with open(IDENTITY_FILE, 'w') as f:
            json.dump(STATE["identity"], f, indent=2)
    except Exception as e:
        logger.warning(f"Identity save failed: {e}")

def update_identity(**kwargs) -> None:
    """
    Update identity fields. Only saves if at least one field actually changed.
    Accepted kwargs: name, preferred_address, response_style, challenge_preference
    """
    updated = False
    for key, value in kwargs.items():
        if key in STATE["identity"] and value is not None:
            STATE["identity"][key] = value
            updated = True
    if updated:
        save_identity()

def get_name() -> Optional[str]:
    """Read-only access to the user's remembered name."""
    return STATE["identity"].get("name")

# =============================================================================
# 🔊 TTS — NON-BLOCKING TEXT-TO-SPEECH
# Runs in a daemon thread so it never blocks the async pipeline.
# =============================================================================
def speak_async(text: str) -> None:
    """
    Convert text to speech using Piper TTS and play via pygame.
    Runs in background thread. Never crashes Rexy if something goes wrong.
    Windows note: must wait for pygame to finish before deleting the temp file.
    """
    def _piper_speak():
        filename = tempfile.mktemp(suffix=".wav")
        try:
            cmd = [
                "piper", "--model", "voices/en_US-lessac-medium.onnx",
                "--output_file", filename,
                "--length_scale", "1.2",
                "--noise_scale", "0.4",
                "--noise_w", "0.1"
            ]
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                timeout=8,
                capture_output=True
            ).check_returncode()

            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()

            # ⚠️ Windows file lock fix: wait for playback before unlinking
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)

        except Exception as e:
            logger.debug(f"TTS failed (non-critical): {e}")
        finally:
            try:
                if os.path.exists(filename):
                    os.unlink(filename)
            except Exception:
                pass  # If unlink fails, not a crisis

    threading.Thread(target=_piper_speak, daemon=True).start()

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
  "confidence": 0.95
}

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
    def detect(message: str, history: List[Dict]) -> Dict[str, Any]:
        """
        Run THINK stage. Returns intent_data dict with intent, emotion,
        confidence, and reliability fields.

        Layer 1: Fast deterministic pre-checks (regex, no LLM needed)
        Layer 2: Ollama LLM for everything else
        """
        message_lower = message.lower().strip()

        # ── PRE-CHECK 1: Math expression (digits + operators) ──
        # Catches "10+5", "3 * 4", "100 - 50 / 2" etc.
        if re.search(r'\d[\d\s]*[\+\-\*\/][\d\s]*\d', message_lower):
            return {"intent": "CALCULATOR", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 2: calc/calculate keyword ──
        if re.search(r'\b(calc|calculate)\b', message_lower):
            return {"intent": "CALCULATOR", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 3: Explicit search trigger ──
        # "search X", "look up X", "google X" → always WEB_SEARCH
        if re.search(r'^\s*(search|look\s*up|google)\b', message_lower):
            return {"intent": "WEB_SEARCH", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 4: Inbox → FILE_READ ──
        if re.search(r'\binbox\b', message_lower):
            return {"intent": "FILE_READ", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 5: "memory usage" → SYSTEM_INFO (hardware, not memory plugin) ──
        if re.search(r'\bmemory\s+usage\b', message_lower):
            return {"intent": "SYSTEM_INFO", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 6: "what time is it in X" → CHAT (timezone question, not local time) ──
        # Must come BEFORE the general GET_TIME check
        if re.search(r'\bwhat time is it\s+in\s+\w+', message_lower):
            return {"intent": "CHAT", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 7: "what time is it" → GET_TIME (local time) ──
        if re.search(r'\bwhat time is it\b', message_lower):
            return {"intent": "GET_TIME", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 8: Weather keywords ──
        if re.search(r'\b(weather|temperature|forecast|is it raining)\b', message_lower):
            return {"intent": "WEATHER", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── PRE-CHECK 9: Explicit memory phrases ──
        if re.search(r'\b(remember that|remind me|don\'t forget|what do you remember|forget about)\b', message_lower):
            return {"intent": "MEMORY", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}
        
        # ── PRE-CHECK 10: State/mode commands → CHAT (not MEMORY) ──
        if re.search(r'\b(go to|switch to|set|enter)\b.{0,20}\b(state|mode)\b', message_lower):
            return {"intent": "CHAT", "emotion": "neutral", "confidence": 0.99, "reliability": "HIGH"}

        # ── LLM DETECTION (Ollama) ──
        # Only runs if no pre-check matched above
        try:
            recent_history = history[-2:] if history else []
            response = ollama.chat(
                model='llama3.2',
                messages=[
                    {"role": "system", "content": IntentDetector.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Message: '{message}'\n"
                            f"Recent history: {json.dumps(recent_history) if recent_history else 'none'}"
                        )
                    }
                ],
                options={"temperature": 0.1}  # Low temp = consistent classification
            )

            raw = response['message']['content'].strip()

            # Strip markdown fences if Ollama adds them (it sometimes does)
            raw = re.sub(r'```(?:json)?', '', raw).strip()

            result = json.loads(raw)

            intent = result.get("intent", "CHAT").upper()
            if intent not in VALID_INTENTS:
                logger.warning(f"LLM returned unknown intent '{intent}', falling back to CHAT")
                return {
                    "intent": "CHAT",
                    "emotion": "neutral",
                    "confidence": 0.3,
                    "reliability": "MALFORMED_INTENT"
                }

            emotion    = result.get("emotion", "neutral")
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            reliability = "HIGH" if confidence >= CONFIDENCE_THRESHOLD else "LOW"

            return {
                "intent":      intent,
                "emotion":     emotion,
                "confidence":  confidence,
                "reliability": reliability
            }

        except json.JSONDecodeError as e:
            logger.warning(f"IntentDetector JSON parse error: {e}")
            return {"intent": "CHAT", "emotion": "neutral", "confidence": 0.2, "reliability": "JSON_ERROR"}

        except Exception as e:
            logger.warning(f"IntentDetector Ollama error: {e}")
            return {"intent": "CHAT", "emotion": "neutral", "confidence": 0.1, "reliability": f"EXCEPTION:{str(e)[:30]}"}

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
    def execute(intent: str, message: str, emotion: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the appropriate handler for the given intent.
        Returns: {"reply": str, "emotion": str, "state": str}
        """

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
            current_time = datetime.now().strftime("%I:%M %p")
            return {
                "reply": f"🕐 It's {current_time} right now!",
                "emotion": "neutral",
                "state": "speaking"
            }

        # ── PRIORITY 3: LIST_FILES ──
        if intent == "LIST_FILES":
            try:
                files = os.listdir('.')
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

            # Generate response via ChatHandler
            reply = state["chat_handler"].generate_response(message, emotion, intent)

            # Sparingly use name on greetings and genuine encouragement
            name = get_name()
            message_lower = message.lower()
            if name:
                is_greeting = any(w in message_lower for w in ["hello", "hi", "hey", "good morning", "good evening"])
                if is_greeting:
                    reply = f"Hey {name}! {reply}"

            return {
                "reply": reply,
                "emotion": emotion,
                "state": "speaking"
            }

        # ── FALLBACK (shouldn't reach here normally) ──
        if PLUGIN_MANAGER.has(intent):
            return PLUGIN_MANAGER.execute(intent, message, emotion, state)

        logger.warning(f"ExecutionEngine received unknown intent: {intent}")
        return {
            "reply": "🤔 I'm not sure what you mean. Try: calc 10+5, time, weather in Ahmedabad, or just chat!",
            "emotion": "neutral",
            "state": "speaking"
        }

# =============================================================================
# 🎯 PENDING STATE MACHINE
# Handles flows that span multiple turns (name confirm, etc.)
# =============================================================================
async def handle_pending(message: str, pending: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Process a message when there's an active pending state.
    Returns a result dict if the pending state handled the message, else None.
    """
    message_lower = message.lower().strip()
    status = pending.get("status")

    # ── Name confirmation flow ──
    if status == "awaiting_name_confirm":
        if any(w in message_lower for w in ["yes", "yeah", "yep", "confirm", "ok", "sure"]):
            update_identity(name=pending["name"])
            STATE["pending"] = None
            return {
                "reply": f"✅ Got it! I'll remember you as {pending['name']}. 😊",
                "emotion": "happy",
                "state": "speaking"
            }
        elif any(w in message_lower for w in ["no", "nope", "cancel", "nah"]):
            STATE["pending"] = None
            return {"reply": "No problem! 😊", "emotion": "neutral", "state": "speaking"}
        else:
            # Retry
            pending["retry_count"] += 1
            if pending["retry_count"] >= pending["max_retries"]:
                STATE["pending"] = None
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
    STATE["pending"] = None
    return None

# =============================================================================
# 🎯 MAIN PIPELINE: process_message
# THINK → VERIFY → EXECUTE, every single time.
# =============================================================================
async def process_message(message: str) -> Dict[str, Any]:
    """
    The full THINK → VERIFY → EXECUTE pipeline.
    This is the only path a message should travel through.
    Returns: {"reply", "emotion", "state"}
    """
    global STATE

    try:
        STATE["turn_id"] += 1
        logger.info(f"TURN {STATE['turn_id']} | '{message[:60]}'")

        # ── STEP 0: Check active pending state first ──
        # If we're waiting for a name confirmation etc., handle that before anything else.
        if STATE.get("pending"):
            pending_result = await handle_pending(message, STATE["pending"])
            if pending_result:
                return pending_result
            # If pending returned None, the pending state was cleared — continue normally

        # ── STEP 0.5: CALCULATOR CHAIN MODE PRE-CHECK ──
        # If we're already in calculator mode, intercept before hitting Ollama.
        # Handles: "*10", "times 3", "divide by 2", "+ 50" etc.
        if STATE["intent"].get("mode") == "calculator":
            chain_triggers = re.search(
                r'(\b(times|multiply|divide|plus|minus|add|subtract)\b|^[\+\-\*\/]\s*\d)',
                message.lower().strip()
            )
            pure_op = re.match(r'^[\+\-\*\/]\s*\d', message.strip())
            
            if chain_triggers or pure_op:
                from modules.calculator import CalculatorHandler
                calc   = CalculatorHandler()
                result = calc.process(message, STATE)
                STATE["intent"]["mode"]        = result.get("mode", "calculator")
                STATE["intent"]["last_result"] = result.get("last_result")
                return {
                    "reply":   result["reply"],
                    "emotion": "thinking",
                    "state":   result.get("state", "thinking")
                }
            
        # ── STEP 1: THINK — detect intent ──
        intent_data = IntentDetector.detect(message, STATE["memory"]["chat_history"])
        logger.info(
            f"THINK | intent={intent_data['intent']} | "
            f"confidence={intent_data['confidence']:.2f} | "
            f"reliability={intent_data['reliability']}"
        )
        emit("INTENT_LOCKED", {
            "intent":      intent_data["intent"],
            "confidence":  intent_data["confidence"],
            "reliability": intent_data["reliability"],
            "turn":        STATE["turn_id"]
        })

        # ── STEP 2: VERIFY — safety check ──
        verification = SafetyVerifier.verify(intent_data)
        logger.info(f"VERIFY | decision={verification['decision']} | reason={verification['reason']}")
        emit("SAFETY_CHECK", {
            "decision": verification["decision"],
            "reason":   verification["reason"],
            "turn":     STATE["turn_id"]
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
                "state": "speaking"
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
            STATE
        )
        logger.info(f"EXECUTE | {intent_data['intent']} → '{result['reply'][:60]}'")
        emit("EXECUTION_RESULT", {
            "intent": intent_data["intent"],
            "reply":  result["reply"][:80],
            "turn":   STATE["turn_id"]
        })

        # ── STEP 4: Update memory (single write after execution) ──
        # Track emotion history
        STATE["memory"]["emotions"].append({
            "type":   result["emotion"],
            "turn":   STATE["turn_id"],
            "intent": intent_data["intent"]
        })
        STATE["memory"]["emotions"] = STATE["memory"]["emotions"][-EMOTION_HISTORY_LIMIT:]

        # Append to chat history for context on next turn
        STATE["memory"]["chat_history"].extend([
            {"role": "user",      "content": message},
            {"role": "assistant", "content": result["reply"]}
        ])
        STATE["memory"]["chat_history"] = STATE["memory"]["chat_history"][-CHAT_HISTORY_LIMIT:]

        STATE["intent"]["last_intent"] = intent_data["intent"]

        return {
            "reply":   result["reply"],
            "emotion": result["emotion"],
            "state":   result.get("state", "speaking")
        }

    except Exception as e:
        logger.critical(f"PIPELINE CRASH: {e}", exc_info=True)
        return _safe_fallback(message)

def _safe_fallback(message: str) -> Dict[str, Any]:
    """
    Last-resort fallback. Clears any dangerous pending state.
    Rexy should NEVER crash — she just lands here instead.
    """
    STATE["pending"] = None
    logger.critical(f"SAFETY_FALLBACK triggered | message='{message[:50]}'")
    return {
        "reply": "🔒 Something went wrong on my end. Try: calc, time, files, or just chat!",
        "emotion": "neutral",
        "state": "idle"
    }

# =============================================================================
# 🌐 FASTAPI APPLICATION + WEBSOCKET
# =============================================================================
load_dotenv()
load_identity()

PLUGIN_MANAGER = PluginManager()
PLUGIN_MANAGER.load_all()
VALID_INTENTS.update(PLUGIN_MANAGER.get_all_intents())
INTENT_RISK.update(PLUGIN_MANAGER.get_risk_levels())

app = FastAPI(title="Rexy AI Assistant", version="4.0")

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

    # Reset session-specific state on new connection
    STATE["intent"]["mode"]        = "chat"
    STATE["intent"]["last_result"] = None
    STATE["pending"]               = None
    STATE["chat_handler"]          = None  # Fresh ChatHandler per session

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            message = payload.get("message", "").strip()

            if not message:
                continue

            logger.info(f"USER: {message}")
            result = await process_message(message)

            response = {
                "reply":   result["reply"],
                "emotion": result["emotion"],
                "state":   result["state"],
                "turn_id": STATE["turn_id"]
            }

            logger.info(f"REXY: {result['reply'][:60]}")
            await websocket.send_text(json.dumps(response))
            speak_async(result["reply"])

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)

# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    print("🚀 Starting Rexy v4.0 — THINK → VERIFY → EXECUTE")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
