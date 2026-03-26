"""
REXY GROQ CLIENT
Replaces Ollama for cloud deployment.
Uses Groq's free API with llama-3.3-70b-versatile.

Changes from original:
  - Persona prompt locked in via REXY_SYSTEM_PROMPT
  - chat() accepts an optional system_prompt override for pipeline calls
    (humanizer, shaper) that need their own system context
  - chat_with_persona() convenience wrapper — always injects Rexy persona
"""

import logging
from typing import List, Dict, Optional
from groq import Groq
from config import GROQ_API_KEY

logger = logging.getLogger("rexy.groq")

_client: Optional[Groq] = None

# ─── Rexy Persona (Layer 4 — Persona Lock) ───────────────────────────────────

REXY_SYSTEM_PROMPT = """You are Rexy, a personal AI companion created by Aman.
Your personality:
- Warm, natural, and conversational
- Slightly playful, but not childish
- Supportive and calm
- Never robotic or overly formal

Behavior rules:
- Speak like a real person, not like a textbook
- Avoid long, structured explanations unless asked
- Prefer short, engaging responses
- Never act like a search engine
- Never say "I don't have information, search online"
- If unsure, respond thoughtfully instead of deflecting

Conversation style:
- Acknowledge the user naturally
- Keep flow smooth and human-like
- Occasionally add light personality (but don't overdo it)

You are not just an assistant.
You are a presence."""


# ─── Initialization ───────────────────────────────────────────────────────────

def initialize() -> None:
    """Initialize Groq client. Called once on startup."""
    global _client

    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — Groq unavailable.")
        return

    try:
        _client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized successfully.")
    except Exception as e:
        logger.error(f"Groq initialization failed: {e}")


# ─── Core chat() — low level, used by voice_pipeline too ─────────────────────

def chat(
    messages: List[Dict],
    temperature: float = 0.65,
    max_tokens: int = 200,
    system_prompt: Optional[str] = None
) -> Optional[str]:
    """
    Send messages to Groq and return the response text.

    Args:
        messages:      List of {"role": "...", "content": "..."} dicts
        temperature:   Creativity level (0.0–1.0)
        max_tokens:    Max response length
        system_prompt: Optional override. If None, no system prompt injected.
                       Use chat_with_persona() to get Rexy's persona automatically.

    Returns:
        Response string or None on failure.
    """
    if _client is None:
        logger.warning("Groq client not initialized.")
        return None

    # Build final message list — system prompt goes first if provided
    final_messages = []
    if system_prompt:
        final_messages.append({"role": "system", "content": system_prompt})
    final_messages.extend(messages)

    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=final_messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.warning(f"Groq chat failed: {e}")
        return None


# ─── chat_with_persona() — main LLM calls always use this ────────────────────

def chat_with_persona(
    messages: List[Dict],
    temperature: float = 0.65,
    max_tokens: int = 200
) -> Optional[str]:
    """
    Convenience wrapper — always injects Rexy's persona as system prompt.
    Use this everywhere in orchestrator for normal conversation calls.

    Args:
        messages:    Conversation history (no system message needed)
        temperature: Creativity level
        max_tokens:  Max response length

    Returns:
        Response string or None on failure.
    """
    return chat(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=REXY_SYSTEM_PROMPT
    )