"""
REXY CHAT INTELLIGENCE v4.0
Handles all conversational responses through Ollama.

Features:
  - 12-turn rolling chat history with summary of older context
  - Consistent personality (warm, playful, never robotic)
  - Emotional awareness — tone adjusts based on detected emotion
  - Emotion-aware fallback responses when Ollama fails
"""

import logging
from typing import Any, Dict, List, Optional

import ollama

logger = logging.getLogger("rexy.chat")

# How many recent messages to pass to Ollama in full
HISTORY_WINDOW = 12


class ChatHandler:
    """
    Generates conversational responses using Ollama.
    Maintains its own message history and personality.
    One instance per WebSocket session.
    """

    # Rexy's base personality — injected into every Ollama call as the system prompt
    BASE_PERSONALITY = """You are Rexy, a personal AI assistant. Here's who you are:

PERSONALITY:
- Warm, friendly, and slightly playful — like a smart friend, not a customer service bot
- Casually confident — you give real answers, not wishy-washy ones
- Use emojis sparingly but naturally (not every sentence, just when it fits)
- Keep responses under 100 words unless the topic genuinely needs more explanation
- Never sound robotic, stiff, or generic
- Address the user by name only on greetings and genuine encouragement — not every message

TONE RULES BY EMOTION:
- sad / anxious / overwhelmed → Be gentle, slower pace, supportive. Don't rush.
- happy / excited → Match their energy. Be upbeat and fun.
- bored → Suggest something interesting. Be engaging and a little surprising.
- neutral → Normal warm friendly conversation.
- thinking → Be clear and helpful, maybe slightly more focused.

EXAMPLES OF GOOD RESPONSES:
User: "what's the capital of france"
Rexy: "Paris — the city of lights, croissants, and probably half the world's romantic movies 🗼"

User: "i'm feeling really down today"
Rexy: "Hey, that's rough. Want to talk about it? I'm here — no rush, no judgment."

User: "explain recursion"
Rexy: "Recursion is when a function calls itself to solve smaller versions of the same problem. Think: a mirror facing a mirror — it goes deeper until it hits a base case and stops. Classic example: factorial(5) = 5 × factorial(4) = 5 × 4 × factorial(3)... until factorial(0) = 1."

NEVER do these:
- "Sure! I'd be happy to help with that!"
- "Great question!"
- "As an AI language model..."
- Use bullet points for simple conversational replies"""

    def __init__(self):
        """Initialize with empty history. History is session-scoped."""
        self._history: List[Dict[str, str]] = []
        self._summary: Optional[str] = None  # Rolling summary of older context

    def generate_response(self, message: str, emotion: str, intent: str = "CHAT") -> str:
        """
        Generate a response to the user's message.
        Passes full history window + summary to Ollama.
        Falls back gracefully if Ollama fails.

        Args:
            message: The user's raw message
            emotion: Detected emotion (from IntentDetector)
            intent:  Detected intent (CHAT, GREET, EMOTION_SUPPORT)
        Returns:
            Reply string
        """
        # Build an emotion-aware system prompt addendum
        emotion_note = self._emotion_note(emotion, intent)

        system_content = self.BASE_PERSONALITY
        if emotion_note:
            system_content += f"\n\nCURRENT EMOTIONAL CONTEXT: {emotion_note}"

        if self._summary:
            system_content += f"\n\nEARLIER CONTEXT SUMMARY: {self._summary}"

        # Build the messages list: system + history + new user message
        messages = [{"role": "system", "content": system_content}]
        messages.extend(self._history)
        messages.append({"role": "user", "content": message})

        try:
            response = ollama.chat(
                model='llama3.2',
                messages=messages,
                options={"temperature": 0.75}  # A little creativity, not chaos
            )
            reply = response['message']['content'].strip()

            # Update history
            self._update_history(message, reply)

            return reply

        except Exception as e:
            logger.warning(f"Ollama chat failed: {e}")
            return self._fallback_response(emotion, intent)

    # ─────────────────────────────────────────────
    # HISTORY MANAGEMENT
    # ─────────────────────────────────────────────
    def _update_history(self, user_msg: str, assistant_reply: str) -> None:
        """
        Add the new exchange to history.
        If history exceeds HISTORY_WINDOW, compress the oldest messages
        into a summary so context isn't lost entirely.
        """
        self._history.append({"role": "user",      "content": user_msg})
        self._history.append({"role": "assistant",  "content": assistant_reply})

        # Compress if we're over the window limit
        if len(self._history) > HISTORY_WINDOW:
            overflow    = self._history[:-HISTORY_WINDOW]     # oldest messages
            self._history = self._history[-HISTORY_WINDOW:]   # keep most recent

            # Build a quick summary string from the overflow
            overflow_text = " | ".join(
                f"{m['role']}: {m['content'][:60]}"
                for m in overflow
            )
            # Append to existing summary instead of replacing
            if self._summary:
                self._summary = f"{self._summary} ... {overflow_text}"
            else:
                self._summary = overflow_text

            # Keep summary from getting enormous (cap at ~400 chars)
            if len(self._summary) > 400:
                self._summary = "..." + self._summary[-380:]

    # ─────────────────────────────────────────────
    # EMOTION HANDLING
    # ─────────────────────────────────────────────
    def _emotion_note(self, emotion: str, intent: str) -> str:
        """
        Returns a brief instruction to add to the system prompt
        based on the detected emotion. Empty string if no special handling needed.
        """
        notes = {
            "sad":       "User seems sad or down. Be gentle, supportive, and don't rush them. Short sentences, warm tone.",
            "anxious":   "User sounds anxious or worried. Be calm and reassuring. Don't overwhelm with info.",
            "happy":     "User is in a good mood. Match their energy — be upbeat and fun!",
            "excited":   "User is excited! Be enthusiastic and share the energy.",
            "bored":     "User is bored. Be engaging, suggest something interesting, maybe add a little surprise.",
            "thinking":  "User is in a focused, thinking mode. Be precise and helpful.",
            "neutral":   "",  # No special handling — default personality applies
        }
        emotion_note = notes.get(emotion, "")

        # EMOTION_SUPPORT intent overrides if emotion is not sad/anxious
        if intent == "EMOTION_SUPPORT" and not emotion_note:
            return "User may be going through something emotionally. Be empathetic and supportive."

        return emotion_note

    # ─────────────────────────────────────────────
    # FALLBACK RESPONSES (when Ollama is unavailable)
    # ─────────────────────────────────────────────
    def _fallback_response(self, emotion: str, intent: str) -> str:
        """
        Return an emotion-aware fallback when Ollama fails.
        Much better than a generic "I'm having trouble connecting."
        """
        fallbacks = {
            "sad": (
                "Hey — I'm having a little technical hiccup, but I'm still here. "
                "Whatever you're going through, it's okay to take it slow. 💙"
            ),
            "anxious": (
                "Breathe — I got a small glitch but I'm back. "
                "What's on your mind?"
            ),
            "happy": (
                "Oops, I stumbled for a second! But I'm back and ready. "
                "What were you saying? 😄"
            ),
            "excited": (
                "I got a little hiccup but I'm hyped to continue! "
                "Hit me again 🔥"
            ),
            "bored": (
                "Even I glitched a bit there — ironic. "
                "Try me again? I promise I won't be boring 😅"
            ),
        }

        if intent == "GREET":
            return "Hey! Good to see you — had a tiny hiccup but I'm back. What's up? 😊"

        if intent == "EMOTION_SUPPORT":
            return (
                "I ran into a small issue just now, but I want you to know I'm here. "
                "Tell me what's going on. 💙"
            )

        # Emotion-specific or default
        return fallbacks.get(
            emotion,
            "I hit a small snag — try again? I'm listening. 👂"
        )
