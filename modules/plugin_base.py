"""
REXY PLUGIN INTERFACE
Every plugin must inherit from RexyPlugin.
Drop your plugin file in modules/plugins/ and Rexy auto-discovers it.

To create a new plugin:
1. Create a file in modules/plugins/ (e.g. weather_plugin.py)
2. Import RexyPlugin from this file
3. Create a class that inherits RexyPlugin
4. Implement all required methods
5. That's it — Rexy finds it automatically on startup
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class RexyPlugin(ABC):
    """
    Base class for all Rexy plugins.
    Every plugin must implement these four methods.
    """

    @property
    @abstractmethod
    def intent_name(self) -> str:
        """
        The intent string this plugin handles.
        Must be UPPERCASE and unique.
        Example: "WEATHER"
        This is what IntentDetector must return to trigger this plugin.
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        One-line description of what this plugin does.
        Used in logs and future help menus.
        Example: "Fetch current weather for a city"
        """
        pass

    @property
    @abstractmethod
    def risk_level(self) -> str:
        """
        Risk level for SafetyVerifier.
        Must be: "low", "medium", or "high"
        Most plugins should be "low".
        """
        pass

    @property
    @abstractmethod
    def intent_examples(self) -> List[str]:
        """
        Example phrases that should trigger this plugin.
        These get injected into IntentDetector's system prompt automatically.
        Example: ["weather in Mumbai", "what's the weather like", "is it raining"]
        """
        pass

    @abstractmethod
    def execute(self, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Run the plugin and return a response.

        Args:
            message: Raw user message
            emotion: Detected emotion string
            state:   Global STATE dict (read/write carefully)
            args:    Structured arguments extracted by Tool Intelligence
                    e.g. {"city": "Tokyo"} for weather
                    Empty dict if no args were extracted (old behaviour)

        Returns:
            Dict with keys:
                "reply"  → string response to show user
                "emotion"→ emotion string for this response
                "state"  → "speaking" | "thinking" | "idle"
        """
        pass
