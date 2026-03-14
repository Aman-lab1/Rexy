"""
REXY GROQ CLIENT
Replaces Ollama for cloud deployment.
Uses Groq's free API with llama3.2 — same model, much faster.
"""

import logging
from typing import List, Dict, Optional
from groq import Groq
from config import GROQ_API_KEY

logger = logging.getLogger("rexy.groq")

_client: Optional[Groq] = None


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


def chat(messages: List[Dict], temperature: float = 0.65) -> Optional[str]:
    """
    Send messages to Groq and return the response text.
    Drop-in replacement for ollama.chat()

    Args:
        messages:    List of {"role": "...", "content": "..."} dicts
        temperature: Creativity level (0.0 - 1.0)

    Returns:
        Response string or None on failure
    """
    if _client is None:
        logger.warning("Groq client not initialized.")
        return None

    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",  
            messages=messages,
            temperature=temperature,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.warning(f"Groq chat failed: {e}")
        return None