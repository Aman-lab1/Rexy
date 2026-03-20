"""
REXY LOCAL AGENT v1.0
Runs on your PC. Connects to Rexy's server and executes local commands.

What it does:
  - Opens apps (browser, VS Code, Spotify, etc.)
  - Controls volume and brightness
  - Takes screenshots

Usage:
    python rexy_local_agent.py

Keep this running in the background whenever you want Rexy to control your PC.
It auto-reconnects if the server restarts.

Requirements:
    pip install websockets pycaw comtypes screen-brightness-control pyautogui pillow

Author: Aman (EEE @ Ahmedabad University)
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("local_agent.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("rexy.local_agent")

# ── Config ────────────────────────────────────────────────────
REXY_WS_URL = "wss://web-production-1c2c75.up.railway.app/ws-agent"
RECONNECT_WAIT = 5
SCREENSHOT_DIR = str(Path.home() / "Pictures" / "Rexy Screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ── Optional dependency flags ─────────────────────────────────
VOLUME_AVAILABLE     = False
BRIGHTNESS_AVAILABLE = False
SCREENSHOT_AVAILABLE = False

# ── Volume ────────────────────────────────────────────────────
VOLUME_AVAILABLE = True

# ── Brightness ────────────────────────────────────────────────
try:
    import screen_brightness_control as _sbc  # type: ignore
    BRIGHTNESS_AVAILABLE = True
except ImportError:
    logger.warning("screen-brightness-control not installed. pip install screen-brightness-control")

# ── Screenshots ───────────────────────────────────────────────
try:
    import pyautogui as _pyautogui    # type: ignore
    SCREENSHOT_AVAILABLE = True
except ImportError:
    logger.warning("pyautogui not installed — screenshots disabled. pip install pyautogui pillow")


# ═══════════════════════════════════════════════════════════════
# APP REGISTRY
# Maps friendly names → executable paths / commands
# Add your own apps here
# ═══════════════════════════════════════════════════════════════
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = "--profile-directory=Default"
PROFILE1 = "--profile-directory=Profile 1"

APP_REGISTRY: dict[str, str] = {
    # Browsers
    "chrome":        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox":       r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "edge":          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",

    # Dev tools
    "vscode":        r"C:\Users\HP\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "vs code":       r"C:\Users\HP\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "terminal":      "wt",
    "cmd":           "cmd",
    "powershell":    "powershell",
    "notepad":       "notepad",

    # Media
    "spotify":       r"C:\Users\HP\AppData\Local\Microsoft\WindowsApps\Spotify.exe",
    "vlc":           r"C:\Program Files\VideoLAN\VLC\vlc.exe",

    # Productivity
    "calculator":    "calc",
    "paint":         "mspaint",
    "word":          r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    "excel":         r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    "notion":        f"{CHROME} --app=https://www.notion.so {PROFILE1}",

    # System
    "task manager":  "taskmgr",
    "file explorer": "explorer",
    "settings":      "ms-settings:",

    # Social / Web apps
    "discord":       f"{CHROME} --app=https://discord.com/app {PROFILE}",
    "whatsapp":      f"{CHROME} --app=https://web.whatsapp.com {PROFILE}",
    "youtube":       f"{CHROME} --app=https://youtube.com {PROFILE}",
    "gmail":         f"{CHROME} --app=https://mail.google.com {PROFILE1}",
}


# ═══════════════════════════════════════════════════════════════
# COMMAND EXECUTORS
# ═══════════════════════════════════════════════════════════════

def open_app(app_name: str) -> dict:
    """Open an application by name."""
    app_lower = app_name.lower().strip()

    path = APP_REGISTRY.get(app_lower)

    # Fuzzy match
    if not path:
        for key, val in APP_REGISTRY.items():
            if app_lower in key or key in app_lower:
                path = val
                break

    if not path:
        return {
            "success": False,
            "message": (
                f"I don't know how to open '{app_name}'. "
                f"Add it to APP_REGISTRY in rexy_local_agent.py"
            )
        }

    try:
        if path.startswith("ms-"):
            os.startfile(path)
        elif "--app=" in path:
            # Chrome web app — split into list to handle spaces correctly
            parts = path.split(" ")
            subprocess.Popen(parts, shell=False)
        else:
            subprocess.Popen(path, shell=True)

        logger.info(f"Opened: {app_name}")
        return {"success": True, "message": f"✅ Opened {app_name.title()}"}

    except Exception as e:
        logger.error(f"open_app failed for '{app_name}': {e}")
        return {"success": False, "message": f"❌ Couldn't open {app_name}: {str(e)[:60]}"}


_current_volume: int = 50

def set_volume(level: int) -> dict:
    global _current_volume        # ← this line must be here
    level = max(0, min(100, level))
    try:
        subprocess.run(
            f'powershell -c "$obj = New-Object -ComObject WScript.Shell; '
            f'1..50 | ForEach-Object {{ $obj.SendKeys([char]174) }}; '
            f'$steps = [math]::Round({level / 100.0} * 50); '
            f'1..$steps | ForEach-Object {{ $obj.SendKeys([char]175) }}"',
            shell=True, capture_output=True, timeout=5
        )
        _current_volume = level   # ← must be inside try, after subprocess
        logger.info(f"Volume set to {level}%")
        return {"success": True, "message": f"🔊 Volume set to {level}%"}
    except Exception as e:
        return {"success": False, "message": f"❌ Volume failed: {str(e)[:80]}"}

def get_volume() -> dict:
    return {
        "success": True,
        "message": f"🔊 Volume is at {_current_volume}%",
        "value":   _current_volume
    }

def set_brightness(level: int) -> dict:
    """Set screen brightness (0-100)."""
    if not BRIGHTNESS_AVAILABLE:
        return {"success": False, "message": "❌ Brightness control not available. pip install screen-brightness-control"}

    level = max(0, min(100, level))
    try:
        _sbc.set_brightness(level)
        logger.info(f"Brightness set to {level}%")
        return {"success": True, "message": f"💡 Brightness set to {level}%"}
    except Exception as e:
        logger.error(f"set_brightness failed: {e}")
        return {"success": False, "message": f"❌ Brightness control failed: {str(e)[:60]}"}


def get_brightness() -> dict:
    """Get current screen brightness."""
    if not BRIGHTNESS_AVAILABLE:
        return {"success": False, "message": "❌ Brightness control not available."}
    try:
        level = _sbc.get_brightness()[0]
        return {"success": True, "message": f"💡 Brightness is at {level}%", "value": level}
    except Exception as e:
        return {"success": False, "message": f"❌ Couldn't get brightness: {str(e)[:60]}"}


def take_screenshot(filename: str = "") -> dict:
    """Take a screenshot and save it."""
    if not SCREENSHOT_AVAILABLE:
        return {"success": False, "message": "❌ Screenshots not available. pip install pyautogui pillow"}

    try:
        if not filename:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not filename.endswith(".png"):
            filename += ".png"

        filepath   = os.path.join(SCREENSHOT_DIR, filename)
        screenshot = _pyautogui.screenshot()
        screenshot.save(filepath)

        logger.info(f"Screenshot saved: {filepath}")
        return {
            "success": True,
            "message": f"📸 Screenshot saved:\n{filepath}",
            "path":    filepath
        }
    except Exception as e:
        logger.error(f"take_screenshot failed: {e}")
        return {"success": False, "message": f"❌ Screenshot failed: {str(e)[:60]}"}


# ═══════════════════════════════════════════════════════════════
# COMMAND ROUTER
# ═══════════════════════════════════════════════════════════════

def execute_command(command: dict) -> dict:
    """
    Route a command dict to the correct executor.

    Supported actions:
        open_app        → {"action": "open_app",       "app": "spotify"}
        set_volume      → {"action": "set_volume",     "level": 50}
        get_volume      → {"action": "get_volume"}
        set_brightness  → {"action": "set_brightness", "level": 70}
        get_brightness  → {"action": "get_brightness"}
        screenshot      → {"action": "screenshot",     "filename": "optional"}
        ping            → {"action": "ping"}
        list_apps       → {"action": "list_apps"}
    """
    action = command.get("action", "").lower()

    if action == "open_app":
        return open_app(command.get("app", ""))

    if action == "set_volume":
        level = command.get("level", 50)
        # Handle relative adjustments from plugin
        if level == "__up__":
            current = get_volume().get("value", 50)
            level   = min(100, int(current) + 20)
        elif level == "__down__":
            current = get_volume().get("value", 50)
            level   = max(0, int(current) - 20)
        return set_volume(int(level))

    if action == "get_volume":
        return get_volume()

    if action == "set_brightness":
        level = command.get("level", 50)
        if level == "__up__":
            current = get_brightness().get("value", 50)
            level   = min(100, int(current) + 20)
        elif level == "__down__":
            current = get_brightness().get("value", 50)
            level   = max(0, int(current) - 20)
        return set_brightness(int(level))

    if action == "get_brightness":
        return get_brightness()

    if action == "screenshot":
        return take_screenshot(command.get("filename", ""))

    if action == "ping":
        return {"success": True, "message": "🟢 Local agent is alive!"}

    if action == "list_apps":
        apps = sorted(APP_REGISTRY.keys())
        return {
            "success": True,
            "message": "Apps I can open:\n" + "\n".join(f"  • {a}" for a in apps)
        }

    return {"success": False, "message": f"❌ Unknown action: '{action}'"}


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET CLIENT
# ═══════════════════════════════════════════════════════════════

async def run_agent() -> None:
    """Main agent loop. Connects to Rexy, processes commands, auto-reconnects."""
    import websockets  # type: ignore

    while True:
        try:
            logger.info(f"Connecting to Rexy at {REXY_WS_URL}...")

            async with websockets.connect(REXY_WS_URL) as ws:
                logger.info("✅ Connected to Rexy server")

                # Announce ourselves
                await ws.send(json.dumps({
                    "type":     "agent_hello",
                    "platform": sys.platform,
                    "version":  "1.0"
                }))

                # Listen for commands
                while True:
                    try:
                        raw = await ws.recv()
                        msg = json.loads(raw)

                        if msg.get("type") == "command":
                            command = msg.get("command", {})
                            cmd_id  = msg.get("cmd_id", "")
                            logger.info(f"Command: {command}")

                            result = execute_command(command)

                            await ws.send(json.dumps({
                                "type":    "result",
                                "cmd_id":  cmd_id,
                                "success": result["success"],
                                "message": result["message"],
                                "data":    {
                                    k: v for k, v in result.items()
                                    if k not in ("success", "message")
                                }
                            }))

                        elif msg.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))

                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from server")

        except Exception as e:
            logger.warning(f"Connection lost: {e}. Reconnecting in {RECONNECT_WAIT}s...")
            await asyncio.sleep(RECONNECT_WAIT)


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  REXY LOCAL AGENT v1.0")
    print("=" * 50)
    print(f"  Connecting to: {REXY_WS_URL}")
    print(f"  Screenshots:   {SCREENSHOT_DIR}")
    print(f"  Volume:        {'✅' if VOLUME_AVAILABLE     else '❌ pip install pycaw comtypes'}")
    print(f"  Brightness:    {'✅' if BRIGHTNESS_AVAILABLE else '❌ pip install screen-brightness-control'}")
    print(f"  Screenshots:   {'✅' if SCREENSHOT_AVAILABLE else '❌ pip install pyautogui pillow'}")
    print("=" * 50 + "\n")

    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n👋 Local agent stopped.")