"""
REXY COMPUTER PLUGIN v1.0
Handles local PC control via the local agent.

Supported commands (all caught by SmartGate):
    Open:       "open spotify", "open chrome", "open VS Code"
    Volume:     "set volume to 50", "volume up", "what's the volume"
    Brightness: "set brightness to 70", "brightness down", "what's the brightness"
    Screenshot: "take a screenshot", "screenshot"

Flow:
    User message
        ↓
    Gate → COMPUTER intent
        ↓
    ComputerPlugin.execute()
        ↓
    Puts command in server queue
        ↓
    rexy_local_agent.py picks it up and executes
        ↓
    Result sent back to user

Author: Aman (EEE @ Ahmedabad University)
"""

import asyncio
import logging
import re
import uuid
from typing import Any, Dict, List, Optional
import nest_asyncio
nest_asyncio.apply()

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.plugins.computer")

# ── Global command queue ──────────────────────────────────────
# ComputerPlugin puts commands here.
# The /ws-agent endpoint in orchestrator.py reads from here.
# Key: cmd_id → asyncio.Future (resolved when agent responds)
_pending_commands: Dict[str, asyncio.Future] = {}
_agent_queue: Optional[asyncio.Queue] = None

def get_agent_queue() -> asyncio.Queue:
    """Get or create the global agent command queue."""
    global _agent_queue
    if _agent_queue is None:
        _agent_queue = asyncio.Queue()
    return _agent_queue


class ComputerPlugin(RexyPlugin):

    # ── RexyPlugin interface ──────────────────────────────────
    @property
    def intent_name(self) -> str:
        return "COMPUTER"

    @property
    def description(self) -> str:
        return "Control your PC — open apps, volume, brightness, screenshots"

    @property
    def risk_level(self) -> str:
        return "low"

    @property
    def intent_examples(self) -> List[str]:
        return [
            "open spotify",
            "set volume to 50",
            "take a screenshot",
            "set brightness to 70",
        ]

    # ── Main execute ─────────────────────────────────────────
    def execute(
        self,
        message: str,
        emotion: str,
        state:   Dict[str, Any],
        args:    Dict[str, Any] = {}
    ) -> Dict[str, Any]:

        # Check if local agent is connected
        if not self._agent_connected():
            return {
                "reply": (
                    "💻 Local agent isn't running.\n"
                    "Start it with:\n"
                    "  python rexy_local_agent.py"
                ),
                "emotion": "neutral",
                "state":   "speaking"
            }

        # Get command from args (SmartGate extracted) or parse from message
        command = args.get("command") or self._parse_command(message)

        if not command:
            return {
                "reply": (
                    "💻 What should I do?\n"
                    "• 'open spotify'\n"
                    "• 'set volume to 60'\n"
                    "• 'take a screenshot'\n"
                    "• 'set brightness to 80'"
                ),
                "emotion": "neutral",
                "state":   "speaking"
            }

        # Send command to local agent and wait for result
        result = self._send_command(command)
        return {
            "reply":   result.get("message", "✅ Done!"),
            "emotion": "happy" if result.get("success") else "neutral",
            "state":   "speaking"
        }

    # ═══════════════════════════════════════════════════════════
    # COMMAND PARSING
    # ═══════════════════════════════════════════════════════════

    def _parse_command(self, message: str) -> Optional[Dict]:
        """Parse natural language into a structured command dict."""
        msg = message.lower().strip()

        # ── OPEN APP ─────────────────────────────────────────
        open_match = re.search(
            r'\b(open|launch|start|run)\s+(.+?)(?:\s*$|\s+for\s|\s+and\s)',
            msg
        )
        if open_match:
            app = open_match.group(2).strip()
            return {"action": "open_app", "app": app}

        # ── VOLUME ───────────────────────────────────────────
        # "set volume to 50", "volume 70", "volume up/down"
        vol_set = re.search(r'\bvolume\s+(?:to\s+)?(\d+)', msg)
        if vol_set:
            return {"action": "set_volume", "level": int(vol_set.group(1))}

        if re.search(r'\bvolume\s+up\b', msg):
            return {"action": "set_volume", "level": self._relative_volume(+20)}

        if re.search(r'\bvolume\s+down\b', msg):
            return {"action": "set_volume", "level": self._relative_volume(-20)}

        if re.search(r'\b(mute|silence)\b', msg):
            return {"action": "set_volume", "level": 0}

        if re.search(r'\b(what.?s|get|check)\s+(the\s+)?volume\b', msg):
            return {"action": "get_volume"}

        # ── BRIGHTNESS ───────────────────────────────────────
        bright_set = re.search(r'\bbrightness\s+(?:to\s+)?(\d+)', msg)
        if bright_set:
            return {"action": "set_brightness", "level": int(bright_set.group(1))}

        if re.search(r'\bbrightness\s+up\b', msg):
            return {"action": "set_brightness", "level": self._relative_brightness(+20)}

        if re.search(r'\bbrightness\s+down\b', msg):
            return {"action": "set_brightness", "level": self._relative_brightness(-20)}

        if re.search(r'\b(what.?s|get|check)\s+(the\s+)?brightness\b', msg):
            return {"action": "get_brightness"}

        # ── SCREENSHOT ───────────────────────────────────────
        if re.search(r'\b(screenshot|screen\s+shot|capture\s+screen|take\s+a\s+screenshot)\b', msg):
            # Optional filename: "screenshot called homework"
            name_match = re.search(r'\b(?:called|named|save\s+as)\s+["\']?(\w[\w\s\-]{0,20})["\']?', msg)
            filename = name_match.group(1).strip() if name_match else ""
            return {"action": "screenshot", "filename": filename}

        # ── LIST APPS ────────────────────────────────────────
        if re.search(r'\b(what\s+apps|list\s+apps|which\s+apps)\b', msg):
            return {"action": "list_apps"}

        return None

    def _relative_volume(self, delta: int) -> int:
        """Calculate new volume level relative to current. Clamps 0-100."""
        try:
            result = self._send_command({"action": "get_volume"}, timeout=2.0)
            current = result.get("data", {}).get("value", 50)
            return max(0, min(100, int(current) + delta))
        except Exception:
            return max(0, min(100, 50 + delta))

    def _relative_brightness(self, delta: int) -> int:
        """Calculate new brightness level relative to current. Clamps 0-100."""
        try:
            result = self._send_command({"action": "get_brightness"}, timeout=2.0)
            current = result.get("data", {}).get("value", 50)
            return max(0, min(100, int(current) + delta))
        except Exception:
            return max(0, min(100, 50 + delta))

    # ═══════════════════════════════════════════════════════════
    # AGENT COMMUNICATION
    # ═══════════════════════════════════════════════════════════

    def _agent_connected(self) -> bool:
        """Check if a local agent is currently connected."""
        from modules.plugins.computer_plugin import _connected_agents
        return len(_connected_agents) > 0

    def _send_command(self, command: Dict, timeout: float = 15.0) -> Dict:
        """
        Send a command to the local agent and wait for the result.
        Uses asyncio to bridge the sync plugin interface with the async WebSocket.
        Times out after `timeout` seconds.
        """
        cmd_id = ""
        try:
            loop   = asyncio.get_event_loop()
            cmd_id = str(uuid.uuid4())[:8]

            # Create a future to wait for the result
            future: asyncio.Future = loop.create_future()
            _pending_commands[cmd_id] = future

            # Put command in queue for the agent WebSocket handler to pick up
            queue = get_agent_queue()
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"cmd_id": cmd_id, "command": command}
            )

            # Wait for result (with timeout)
            result = loop.run_until_complete(
                asyncio.wait_for(future, timeout=timeout)
            )
            return result

        except asyncio.TimeoutError:
            logger.warning(f"Command timed out: {command}")
            return {"success": False, "message": "⏳ Local agent didn't respond in time. Is it running?"}
        except Exception as e:
            logger.error(f"_send_command failed: {e}")
            return {"success": False, "message": f"❌ Command failed: {str(e)[:60]}"}
        finally:
            _pending_commands.pop(cmd_id, None)


# ── Connected agents registry ─────────────────────────────────
# Populated by the /ws-agent WebSocket handler in orchestrator.py
_connected_agents = set()