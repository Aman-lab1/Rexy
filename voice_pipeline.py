"""
REXY VOICE PIPELINE
Pre- and post-processing layer for voice input/output.
Sits between STT → Orchestrator → TTS.

Layers:
  1. humanize_input()   — cleans noisy speech before LLM sees it
  2. check_confidence() — gates garbage input before it hits main LLM
  3. shape_response()   — smooths robotic output before it reaches the user
"""

import logging
import re
from typing import Tuple

import groq_client

logger = logging.getLogger("rexy.voice_pipeline")

# ─── Tunables ────────────────────────────────────────────────────────────────

# Minimum word count to pass the confidence filter
MIN_WORDS = 2

# Words that alone are too ambiguous to process
AMBIGUOUS_FRAGMENTS = {"what", "why", "how", "huh", "um", "uh", "yeah", "okay", "ok"}

# Soft fallback Rexy says when input is too unclear
UNCLEAR_REPLY = "Hmm, I didn't quite catch that — could you say it again?"

# ─── Layer 1: Input Humanizer ─────────────────────────────────────────────────

HUMANIZER_PROMPT = """You are a speech correction assistant.
Your task is to convert noisy, error-prone spoken input into a clean, natural sentence.
Rules:
- Preserve the original meaning strictly
- Do NOT add new intent or assumptions
- Fix grammar, spacing, and obvious phonetic mistakes
- Keep casual tone (do not make it overly formal)
- If input is already clear, return it unchanged
- If input is too unclear to fix, return it exactly as-is
Input:
"{user_input}"
Output:
Only return the corrected sentence. No explanation."""


def humanize_input(text: str) -> str:
    """
    Clean noisy STT output into natural language before the main LLM sees it.
    Uses a small, low-temperature Groq call for stability.

    Returns the cleaned text, or the original if the call fails.
    """
    if not text or not text.strip():
        return text

    prompt = HUMANIZER_PROMPT.format(user_input=text.strip())

    result = groq_client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,        # low — we want correction, not creativity
        max_tokens=80           # short output only
    )

    if result and result.strip():
        cleaned = result.strip().strip('"').strip("'")
        logger.debug(f"Humanizer: '{text}' → '{cleaned}'")
        return cleaned

    # Fallback: return original if call fails
    logger.warning("Humanizer call failed — using raw input.")
    return text


# ─── Layer 2: Confidence Filter ───────────────────────────────────────────────

def check_confidence(text: str) -> Tuple[bool, str]:
    """
    Gate noisy or ambiguous input before it reaches the main LLM.

    Returns:
        (should_proceed: bool, fallback_reply: str)
        If should_proceed is True  → pass text to main LLM normally
        If should_proceed is False → send fallback_reply directly to user
    """
    if not text or not text.strip():
        return False, UNCLEAR_REPLY

    words = text.strip().split()

    # Too short
    if len(words) < MIN_WORDS:
        stripped = text.strip().lower().rstrip("?.!")
        if stripped in AMBIGUOUS_FRAGMENTS:
            return False, UNCLEAR_REPLY

    # Mostly non-alphabetic (garbled audio artifacts)
    alpha_ratio = sum(c.isalpha() for c in text) / max(len(text), 1)
    if alpha_ratio < 0.5:
        logger.debug(f"Confidence filter blocked (alpha ratio {alpha_ratio:.2f}): '{text}'")
        return False, UNCLEAR_REPLY

    # Repetitive garbage (e.g. "the the the the")
    unique_ratio = len(set(words)) / len(words)
    if len(words) >= 4 and unique_ratio < 0.35:
        logger.debug(f"Confidence filter blocked (repetitive): '{text}'")
        return False, UNCLEAR_REPLY

    return True, ""


# ─── Layer 3: Response Shaper ─────────────────────────────────────────────────

SHAPER_PROMPT = """You are a response refiner.
Rewrite the given response to sound natural, conversational, and human-like.
Rules:
- Keep the meaning exactly the same
- Make tone casual and smooth
- Remove robotic or overly formal phrasing
- Keep it concise (avoid long paragraphs)
- Do not add new information
Input:
"{llm_output}"
Output:
Only return the improved response."""


def shape_response(text: str) -> str:
    """
    Post-process the main LLM's reply to smooth out robotic phrasing.
    Only runs if the response looks like it needs shaping (length check).

    Returns shaped text, or original if call fails.
    """
    if not text or not text.strip():
        return text

    # Skip shaping for very short replies — they're usually fine
    if len(text.split()) < 12:
        return text

    prompt = SHAPER_PROMPT.format(llm_output=text.strip())

    result = groq_client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,        # slightly more natural than humanizer
        max_tokens=300
    )

    if result and result.strip():
        shaped = result.strip().strip('"').strip("'")
        logger.debug(f"Shaper applied: {len(text)} → {len(shaped)} chars")
        return shaped

    logger.warning("Shaper call failed — using raw LLM output.")
    return text


# ─── Convenience: full input pipeline ────────────────────────────────────────

def process_input(raw_text: str) -> Tuple[bool, str, str]:
    """
    Run the full input pipeline: humanize → confidence check.

    Returns:
        (should_proceed: bool, cleaned_text: str, fallback_reply: str)

    Usage in orchestrator:
        proceed, text, fallback = voice_pipeline.process_input(raw)
        if not proceed:
            return fallback   # send directly to user
        # else use text as normal
    """
    cleaned = humanize_input(raw_text)
    proceed, fallback = check_confidence(cleaned)
    return proceed, cleaned, fallback