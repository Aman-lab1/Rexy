"""
REXY WEB SEARCH PLUGIN
Searches the web using DuckDuckGo's free Instant Answer API.
No API key needed. No account needed.

Handles:
- "search for python tutorials"
- "look up Nikola Tesla"
- "google latest AI news"
- "find information about black holes"
"""

import re
import json
import logging
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Optional

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.websearch")

# DuckDuckGo Instant Answer API — free, no key required
DDG_API = "https://api.duckduckgo.com/?q={}&format=json&no_redirect=1&no_html=1&skip_disambig=1"


class WebSearchPlugin(RexyPlugin):
    """Search the web using DuckDuckGo and return a clean summary."""

    @property
    def intent_name(self) -> str:
        return "WEB_SEARCH"

    @property
    def description(self) -> str:
        return "Search the web using DuckDuckGo for any topic"

    @property
    def risk_level(self) -> str:
        return "low"

    @property
    def intent_examples(self) -> List[str]:
        return [
            "search for python tutorials",
            "look up Nikola Tesla",
            "find information about black holes",
            "google latest AI news",
        ]

    # ── Main execute ──
    def execute(self, message: str, emotion: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Extract query, search DuckDuckGo, return formatted result."""
        query = self._extract_query(message)

        if not query:
            return {
                "reply": "🔍 What should I search for?",
                "emotion": "neutral",
                "state": "speaking"
            }

        logger.info(f"Web search: '{query}'")
        result = self._search(query)

        if result is None:
            encoded = urllib.parse.quote(query)
            return {
                "reply": (
                    f"🔍 No instant answer found for '{query}'.\n"
                    f"Try searching directly: https://duckduckgo.com/?q={encoded}"
                ),
                "emotion": "neutral",
                "state": "speaking"
            }

        return {
            "reply": result,
            "emotion": "neutral",
            "state": "speaking"
        }

    # ── Query extraction ──
    def _extract_query(self, message: str) -> str:
        """
        Strip trigger words and return the actual search query.
        "search for black holes" → "black holes"
        "look up Nikola Tesla"   → "Nikola Tesla"
        "google AI news"         → "AI news"
        """
        # Remove trigger phrases
        cleaned = re.sub(
            r'^\s*(search(\s+for|\s+about)?|look\s+up|google|find(\s+information(\s+about)?)?|'
            r'look\s+for|browse(\s+for)?|what\s+is|who\s+is|tell\s+me\s+about)\s+',
            '',
            message,
            flags=re.IGNORECASE
        ).strip()

        # Remove trailing punctuation
        cleaned = re.sub(r'[?!.]+$', '', cleaned).strip()

        return cleaned if len(cleaned) > 1 else ""

    # ── DuckDuckGo API call ──
    def _search(self, query: str) -> Optional[str]:
        """
        Call DuckDuckGo Instant Answer API.
        Returns a formatted string reply or None if nothing useful found.
        """
        try:
            encoded = urllib.parse.quote(query)
            url     = DDG_API.format(encoded)

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Rexy/4.0 (personal assistant)"}
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                raw  = response.read().decode("utf-8")
                data = json.loads(raw)

            # ── Try Abstract (Wikipedia-style summary) ──
            abstract = data.get("AbstractText", "").strip()
            source   = data.get("AbstractSource", "")
            abstract_url = data.get("AbstractURL", "")

            if abstract:
                reply = f"🔍 **{query.title()}**\n\n{abstract}"
                if source:
                    reply += f"\n\n📖 Source: {source}"
                    if abstract_url:
                        reply += f" — {abstract_url}"
                return reply

            # ── Try Answer (instant fact) ──
            answer = data.get("Answer", "").strip()
            if answer:
                return f"🔍 {answer}"

            # ── Try Definition ──
            definition = data.get("Definition", "").strip()
            def_source = data.get("DefinitionSource", "")
            if definition:
                reply = f"📖 **{query.title()}**: {definition}"
                if def_source:
                    reply += f"\n— {def_source}"
                return reply

            # ── Try Related Topics ──
            topics = data.get("RelatedTopics", [])
            snippets = []
            for topic in topics[:3]:
                # Topics can be nested dicts or have a "Topics" sub-list
                if isinstance(topic, dict):
                    text = topic.get("Text", "").strip()
                    if text and len(text) > 20:
                        snippets.append(f"• {text[:120]}")

            if snippets:
                reply = f"🔍 Results for **'{query}'**:\n\n" + "\n".join(snippets)
                reply += f"\n\n🌐 More: https://duckduckgo.com/?q={urllib.parse.quote(query)}"
                return reply

            # Nothing useful found
            return None

        except Exception as e:
            logger.warning(f"Web search failed for '{query}': {e}")
            return None