"""
REXY PLUGIN MANAGER
Auto-discovers all plugins in modules/plugins/ on startup.
No manual registration needed — drop a file, Rexy finds it.

Usage in orchestrator.py:
    from modules.plugin_manager import PluginManager
    pm = PluginManager()
    pm.load_all()

Then in ExecutionEngine:
    if pm.has(intent):
        return pm.execute(intent, message, emotion, state)
"""

import os
import importlib
import inspect
import logging
from typing import Any, Dict, Optional

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.plugins")

# Folder where plugin files live
PLUGINS_DIR = os.path.join(os.path.dirname(__file__), "plugins")


class PluginManager:
    """
    Scans modules/plugins/ for any file ending in _plugin.py,
    imports it, finds the class that inherits RexyPlugin,
    and registers it by intent_name.

    One instance lives in orchestrator.py and gets used by ExecutionEngine.
    """

    def __init__(self):
        # Dict mapping intent_name → plugin instance
        # Example: {"WEATHER": <WeatherPlugin>}
        self._plugins: Dict[str, RexyPlugin] = {}

    def load_all(self) -> None:
        """
        Scan PLUGINS_DIR and load every valid plugin file.
        Called once on startup.
        """
        if not os.path.exists(PLUGINS_DIR):
            logger.warning(f"Plugins directory not found: {PLUGINS_DIR}")
            return

        loaded = 0
        for filename in os.listdir(PLUGINS_DIR):
            # Only process files ending in _plugin.py
            if not filename.endswith("_plugin.py"):
                continue
            if filename.startswith("_"):
                continue  # skip __init__.py etc.

            module_name = filename[:-3]  # strip .py
            self._load_plugin_file(module_name)
            loaded += 1

        logger.info(f"Plugin manager: {loaded} file(s) scanned, {len(self._plugins)} plugin(s) loaded.")
        if self._plugins:
            logger.info(f"Active plugins: {list(self._plugins.keys())}")

    def _load_plugin_file(self, module_name: str) -> None:
        """
        Import a single plugin file and register any RexyPlugin subclass found inside.
        """
        try:
            # Import as modules.plugins.module_name
            full_module = f"modules.plugins.{module_name}"
            module = importlib.import_module(full_module)

            # Scan all classes in the module
            for _, cls in inspect.getmembers(module, inspect.isclass):
                # Must be a RexyPlugin subclass but not RexyPlugin itself
                if issubclass(cls, RexyPlugin) and cls is not RexyPlugin:
                    try:
                        instance = cls()
                        intent   = instance.intent_name.upper()

                        if intent in self._plugins:
                            logger.warning(f"Duplicate intent '{intent}' from {module_name} — skipping.")
                            continue

                        self._plugins[intent] = instance
                        logger.info(
                            f"✅ Plugin loaded: {cls.__name__} → intent='{intent}' "
                            f"risk='{instance.risk_level}'"
                        )

                    except Exception as e:
                        logger.error(f"Failed to instantiate {cls.__name__}: {e}")

        except Exception as e:
            logger.error(f"Failed to import plugin file '{module_name}': {e}")

    def has(self, intent: str) -> bool:
        """Check if a plugin exists for the given intent."""
        return intent.upper() in self._plugins

    def execute(self, intent: str, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Run the plugin for the given intent.
        Returns a standard result dict: {"reply", "emotion", "state"}
        """
        plugin = self._plugins.get(intent.upper())
        if plugin is None:
            logger.error(f"Plugin execute called for unknown intent: {intent}")
            return {
                "reply": f"❌ No plugin found for '{intent}'.",
                "emotion": "neutral",
                "state": "speaking"
            }
        try:
            return plugin.execute(message, emotion, state, args)
        except Exception as e:
                logger.error(
                    f"Plugin '{intent}' crashed | "
                    f"message='{message[:50]}' | "
                    f"error={type(e).__name__}: {e}"
                )
                return {
                    "reply": "That feature hit a snag. Try again?",
                    "emotion": "neutral",
                    "state": "speaking"
                }

    def get_all_intents(self) -> list:
        """Return list of all registered intent names. Used to update VALID_INTENTS."""
        return list(self._plugins.keys())

    def get_intent_examples(self) -> str:
        """
        Return example phrases from all plugins, formatted for injection
        into IntentDetector's system prompt.
        """
        lines = []
        for intent, plugin in self._plugins.items():
            examples = ", ".join(f'"{e}"' for e in plugin.intent_examples[:3])
            lines.append(f"{intent}: {examples}")
        return "\n".join(lines)

    def get_risk_levels(self) -> Dict[str, str]:
        """Return dict of intent → risk_level for all plugins."""
        return {intent: plugin.risk_level for intent, plugin in self._plugins.items()}
