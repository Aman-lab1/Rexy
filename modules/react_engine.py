"""
REXY ReAct ENGINE
Reason → Act → Observe → Answer

Handles advice/interpretation questions that need:
1. Fetching real data from a plugin
2. LLM interpreting that data conversationally

Examples:
- "should I take an umbrella?" → fetch weather → LLM interprets
- "is my laptop struggling?" → fetch sysinfo → LLM interprets

Author: Aman (EEE @ Ahmedabad University)
"""

import json
import logging
import groq_client
from typing import Any, Dict

logger = logging.getLogger("rexy.react")

# ── Phrases that signal ReAct is needed ──
# User wants advice/interpretation, not raw data
REACT_TRIGGERS = [
    "should i", "should i take", "do i need", "is it safe",
    "would you recommend", "is it good", "is it bad",
    "is my", "how is my", "is it worth", "can i",
    "will it", "is there a chance", "what should i",
    "is it okay", "is it fine", "is it suitable",
    "advise", "suggest", "recommend"
]

# ── Intents that support ReAct interpretation ──
REACT_SUPPORTED_INTENTS = {"WEATHER", "SYSTEM_INFO", "WEB_SEARCH", "FILE_READ"}


class ReActEngine:
    """
    Decides if a question needs ReAct and runs the loop if so.
    
    Flow:
    THOUGHT → which plugin gives me the data I need?
    ACTION  → run that plugin, get raw data
    OBSERVE → what did the plugin return?
    ANSWER  → LLM interprets data into a human response
    """

    @staticmethod
    def needs_react(message: str, intent: str) -> bool:
        """
        Check if this message needs ReAct interpretation.
        Returns True if user wants advice, not raw data.
        """
        # Only supported intents can use ReAct
        if intent not in REACT_SUPPORTED_INTENTS:
            return False

        message_lower = message.lower().strip()
        return any(trigger in message_lower for trigger in REACT_TRIGGERS)

    @staticmethod
    def run(message: str, intent: str, plugin_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the THOUGHT → OBSERVE → ANSWER stage.
        """
        raw_data = plugin_result.get("reply", "")

        logger.info(f"ReAct | OBSERVE | intent={intent} | data_len={len(raw_data)}")

        # ── Intent context map ──
        # Tells the LLM exactly what kind of data it's looking at
        INTENT_CONTEXT = {
            "WEATHER":     "weather data fetched live from wttr.in",
            "SYSTEM_INFO": "system hardware stats fetched live from this laptop",
            "WEB_SEARCH":  "web search results fetched live from DuckDuckGo",
            "FILE_READ":   "file contents read from the user's inbox folder",
        }
        data_context = INTENT_CONTEXT.get(intent, "data fetched from a plugin")

        try:
            # ── STAGE 1: THOUGHT ──
            # LLM reasons about what the user actually needs
            # before looking at the data
            thought_prompt = f"""The user asked: "{message}"

    Think step by step:
    1. What is the user actually asking for? (advice, yes/no, explanation?)
    2. What specific information from the data will answer their question?
    3. What should be ignored?

    Respond ONLY with a short reasoning in 2-3 sentences. No answer yet."""

            thought = groq_client.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Rexy's reasoning engine. "
                            "You think carefully about what the user needs "
                            "before answering. Stay focused only on the user's question."
                        )
                    },
                    {"role": "user", "content": thought_prompt}
                ],
                temperature=0.2
            )
            if thought is None:
                raise Exception("Groq returned None for thought")
            logger.info(f"ReAct | THOUGHT | '{thought[:80]}'")

            # ── STAGE 2: ANSWER ──
            # LLM uses its reasoning + the actual data to answer
            answer_prompt = f"""The user asked: "{message}"

    Your reasoning about what they need:
    {thought}

    Here is the {data_context}:
    {raw_data}

    Now answer the user's question directly using only the data above.
    Be conversational and helpful. Give a clear recommendation if they asked for one.
    2-3 sentences max. Never repeat raw numbers unless they matter to the answer."""

            interpreted = groq_client.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Rexy, a friendly personal AI assistant. "
                            "You answer questions using only the data provided to you. "
                            "Never use outside knowledge or context. "
                            "Never hallucinate. If the data doesn't answer the question, say so."
                        )
                    },
                    {"role": "user", "content": answer_prompt}
                ],
                temperature=0.4
            )
            if interpreted is None:
                raise Exception("Groq returned None for answer")
            logger.info(f"ReAct | ANSWER | '{interpreted[:60]}'")

            return {
                "reply":   interpreted,
                "emotion": "happy",
                "state":   "speaking"
            }

        except Exception as e:
            logger.warning(f"ReAct LLM failed: {e} — falling back to raw plugin result")
            return plugin_result