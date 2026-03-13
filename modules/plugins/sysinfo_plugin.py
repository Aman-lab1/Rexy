"""
REXY SYSTEM INFO PLUGIN
Shows live system stats: CPU, RAM, battery, disk, uptime.
Requires psutil: pip install psutil --break-system-packages

Handles:
- "system info"
- "how much RAM is being used?"
- "what's my CPU usage?"
- "check battery"
- "how much disk space do I have?"
- "how long has my PC been on?"
"""

import logging
from typing import Any, Dict, List

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.sysinfo")


class SystemInfoPlugin(RexyPlugin):
    """Show live system stats using psutil."""

    @property
    def intent_name(self) -> str:
        return "SYSTEM_INFO"

    @property
    def description(self) -> str:
        return "Show CPU, RAM, battery, disk, and uptime stats"

    @property
    def risk_level(self) -> str:
        return "low"

    @property
    def intent_examples(self) -> List[str]:
        return [
            "system info",
            "how much RAM is being used",
            "what's my CPU usage",
            "check battery",
            "how much disk space do I have",
        ]

    # ── Main execute ──
    def execute(self, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """Detect what the user wants and return the relevant stat."""
        try:
            import psutil
        except ImportError:
            return {
                "reply": "❌ psutil not installed. Run: pip install psutil --break-system-packages",
                "emotion": "neutral",
                "state": "speaking"
            }

        message_lower = message.lower()

        # Route to specific stat based on keywords
        if any(w in message_lower for w in ["battery", "charge", "charging"]):
            return self._battery(psutil)

        if any(w in message_lower for w in ["cpu", "processor", "processing"]):
            return self._cpu(psutil)

        if any(w in message_lower for w in ["ram", "memory", "mem"]):
            return self._ram(psutil)

        if any(w in message_lower for w in ["disk", "storage", "space", "drive"]):
            return self._disk(psutil)

        if any(w in message_lower for w in ["uptime", "how long", "boot", "running"]):
            return self._uptime(psutil)

        # Default: show everything
        return self._full_report(psutil)

    # ─────────────────────────────────────────────
    # INDIVIDUAL STATS
    # ─────────────────────────────────────────────
    def _cpu(self, psutil) -> Dict[str, Any]:
        """CPU usage and core count."""
        usage  = psutil.cpu_percent(interval=1)
        cores  = psutil.cpu_count(logical=False)
        threads = psutil.cpu_count(logical=True)
        freq   = psutil.cpu_freq()

        freq_str = f" @ {freq.current:.0f} MHz" if freq else ""
        bar      = self._bar(usage)

        return {
            "reply": (
                f"🖥️ **CPU**\n"
                f"{bar} {usage}%\n"
                f"Cores: {cores} physical / {threads} logical{freq_str}"
            ),
            "emotion": "neutral",
            "state": "speaking"
        }

    def _ram(self, psutil) -> Dict[str, Any]:
        """RAM usage."""
        mem   = psutil.virtual_memory()
        used  = mem.used  / (1024 ** 3)
        total = mem.total / (1024 ** 3)
        bar   = self._bar(mem.percent)

        return {
            "reply": (
                f"🧠 **RAM**\n"
                f"{bar} {mem.percent}%\n"
                f"{used:.1f} GB used / {total:.1f} GB total"
            ),
            "emotion": "neutral",
            "state": "speaking"
        }

    def _disk(self, psutil) -> Dict[str, Any]:
        """Disk usage for C: drive (or root on Linux)."""
        try:
            import sys
            path  = "C:\\" if sys.platform == "win32" else "/"
            disk  = psutil.disk_usage(path)
            used  = disk.used  / (1024 ** 3)
            total = disk.total / (1024 ** 3)
            free  = disk.free  / (1024 ** 3)
            bar   = self._bar(disk.percent)

            return {
                "reply": (
                    f"💾 **Disk ({path})**\n"
                    f"{bar} {disk.percent}%\n"
                    f"{used:.1f} GB used / {total:.1f} GB total\n"
                    f"Free: {free:.1f} GB"
                ),
                "emotion": "neutral",
                "state": "speaking"
            }
        except Exception as e:
            return {"reply": f"❌ Disk info error: {e}", "emotion": "neutral", "state": "speaking"}

    def _battery(self, psutil) -> Dict[str, Any]:
        """Battery status."""
        battery = psutil.sensors_battery()
        if battery is None:
            return {
                "reply": "🔋 No battery found (maybe you're on a desktop?)",
                "emotion": "neutral",
                "state": "speaking"
            }

        percent  = battery.percent
        plugged  = battery.power_plugged
        bar      = self._bar(percent)

        # Estimate time remaining
        secs_left = battery.secsleft
        if plugged:
            time_str = "⚡ Charging"
        elif secs_left == psutil.POWER_TIME_UNLIMITED:
            time_str = "⚡ Fully charged"
        elif secs_left == psutil.POWER_TIME_UNKNOWN:
            time_str = "⏱️ Time unknown"
        else:
            hours   = secs_left // 3600
            minutes = (secs_left % 3600) // 60
            time_str = f"⏱️ ~{hours}h {minutes}m remaining"

        emoji = "🔋" if percent > 20 else "🪫"
        return {
            "reply": (
                f"{emoji} **Battery**\n"
                f"{bar} {percent:.0f}%\n"
                f"{time_str}"
            ),
            "emotion": "neutral",
            "state": "speaking"
        }

    def _uptime(self, psutil) -> Dict[str, Any]:
        """How long the system has been running."""
        import time
        from datetime import datetime

        boot_time    = psutil.boot_time()
        uptime_secs  = time.time() - boot_time
        hours        = int(uptime_secs // 3600)
        minutes      = int((uptime_secs % 3600) // 60)
        boot_str     = datetime.fromtimestamp(boot_time).strftime("%d %b %Y, %I:%M %p")

        return {
            "reply": (
                f"⏱️ **Uptime**\n"
                f"Running for {hours}h {minutes}m\n"
                f"Last boot: {boot_str}"
            ),
            "emotion": "neutral",
            "state": "speaking"
        }

    def _full_report(self, psutil) -> Dict[str, Any]:
        """Show all stats in one compact report."""
        import time, sys
        from datetime import datetime

        # CPU
        cpu_pct  = psutil.cpu_percent(interval=1)

        # RAM
        mem      = psutil.virtual_memory()
        ram_used = mem.used  / (1024 ** 3)
        ram_tot  = mem.total / (1024 ** 3)

        # Disk
        try:
            path  = "C:\\" if sys.platform == "win32" else "/"
            disk  = psutil.disk_usage(path)
            disk_free = disk.free / (1024 ** 3)
            disk_tot  = disk.total / (1024 ** 3)
            disk_str  = f"💾 Disk: {disk_free:.1f} GB free / {disk_tot:.1f} GB"
        except Exception:
            disk_str = "💾 Disk: unavailable"

        # Battery
        battery = psutil.sensors_battery()
        if battery:
            plugged  = "⚡" if battery.power_plugged else "🔋"
            batt_str = f"{plugged} Battery: {battery.percent:.0f}%"
        else:
            batt_str = "🔋 Battery: N/A"

        # Uptime
        uptime_secs = time.time() - psutil.boot_time()
        hours       = int(uptime_secs // 3600)
        minutes     = int((uptime_secs % 3600) // 60)

        return {
            "reply": (
                f"🖥️ **System Info**\n\n"
                f"🖥️ CPU:  {self._bar(cpu_pct)} {cpu_pct}%\n"
                f"🧠 RAM:  {self._bar(mem.percent)} {mem.percent}% ({ram_used:.1f}/{ram_tot:.1f} GB)\n"
                f"{disk_str}\n"
                f"{batt_str}\n"
                f"⏱️ Uptime: {hours}h {minutes}m"
            ),
            "emotion": "neutral",
            "state": "speaking"
        }

    # ─────────────────────────────────────────────
    # HELPER: ASCII progress bar
    # ─────────────────────────────────────────────
    def _bar(self, percent: float, width: int = 10) -> str:
        """
        Visual progress bar using block characters.
        50% → [█████░░░░░]
        """
        filled = int(width * percent / 100)
        empty  = width - filled
        return f"[{'█' * filled}{'░' * empty}]"
