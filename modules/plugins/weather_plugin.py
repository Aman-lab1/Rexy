"""
REXY WEATHER PLUGIN
Fetches current weather using Open-Meteo (free, no API key, server-friendly).

Flow:
1. Geocoding API  → city name → lat/lon
2. Forecast API   → lat/lon  → current weather

Handles:
- "weather in Ahmedabad"
- "what's the weather like in Mumbai"
- "is it raining in Delhi"
- "weather" (uses last known city or asks user)
"""

import re
import logging
import urllib.request
import urllib.parse
import json
from typing import Any, Dict, List

from modules.plugin_base import RexyPlugin

logger = logging.getLogger("rexy.weather")

# WMO weather code → emoji + label
WEATHER_CODES = {
    0:  ("☀️",  "Clear sky"),
    1:  ("🌤️",  "Mainly clear"),
    2:  ("⛅",  "Partly cloudy"),
    3:  ("☁️",  "Overcast"),
    45: ("🌫️",  "Foggy"),
    48: ("🌫️",  "Icy fog"),
    51: ("🌦️",  "Light drizzle"),
    53: ("🌦️",  "Moderate drizzle"),
    55: ("🌧️",  "Dense drizzle"),
    61: ("🌧️",  "Slight rain"),
    63: ("🌧️",  "Moderate rain"),
    65: ("🌧️",  "Heavy rain"),
    71: ("🌨️",  "Slight snow"),
    73: ("❄️",  "Moderate snow"),
    75: ("❄️",  "Heavy snow"),
    77: ("🌨️",  "Snow grains"),
    80: ("🌦️",  "Slight showers"),
    81: ("🌧️",  "Moderate showers"),
    82: ("🌧️",  "Violent showers"),
    85: ("🌨️",  "Slight snow shower"),
    86: ("❄️",  "Heavy snow shower"),
    95: ("⛈️",  "Thunderstorm"),
    96: ("⛈️",  "Thunderstorm with hail"),
    99: ("⛈️",  "Thunderstorm with heavy hail"),
}


class WeatherPlugin(RexyPlugin):
    """Fetches weather from Open-Meteo for any city."""

    # ── Plugin metadata ──
    @property
    def intent_name(self) -> str:
        return "WEATHER"

    @property
    def description(self) -> str:
        return "Fetch current weather for any city using Open-Meteo"

    @property
    def risk_level(self) -> str:
        return "low"

    @property
    def intent_examples(self) -> List[str]:
        return [
            "weather in Ahmedabad",
            "what's the weather like in Mumbai",
            "is it raining in Delhi",
            "weather today",
            "how's the weather",
            "temperature in Bangalore",
        ]

    # ── Main execute ──
    def execute(self, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        city = args.get("city", "").strip()
        if not city:
            city = self._extract_city(message)

        if not city:
            city = state.get("memory", {}).get("last_weather_city")

        if not city:
            return {
                "reply": "🌍 Which city should I check the weather for?",
                "emotion": "neutral",
                "state": "speaking"
            }

        weather_data = self._fetch_weather(city)

        if weather_data is None:
            return {
                "reply": f"❌ Couldn't fetch weather for '{city}'. Check the city name and try again.",
                "emotion": "neutral",
                "state": "speaking"
            }

        if "memory" not in state:
            state["memory"] = {}
        state["memory"]["last_weather_city"] = weather_data["city"]

        return {
            "reply": self._format_reply(weather_data),
            "emotion": "happy",
            "state": "speaking"
        }

    # ── City extraction ──
    def _extract_city(self, message: str) -> str:
        message_clean = message.strip()

        match = re.search(
            r'\b(?:weather|temperature|temp|forecast|climate)\s+(?:in|for|at|of)\s+([A-Za-z\s]+?)(?:\?|$|\.)',
            message_clean, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        match = re.search(
            r'([A-Za-z\s]+?)\s+(?:weather|temperature|temp|forecast)',
            message_clean, re.IGNORECASE
        )
        if match:
            city = match.group(1).strip()
            skip = {"what", "how", "is", "the", "today", "current", "like", "s"}
            if city.lower() not in skip and len(city) > 2:
                return city

        match = re.search(r'\bin\s+([A-Za-z\s]+?)(?:\?|$|\.)', message_clean, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    # ── Step 1: Geocode city → lat/lon ──
    def _geocode(self, city: str) -> Dict[str, Any] | None:
        try:
            encoded = urllib.parse.quote(city)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1&language=en&format=json"
            req = urllib.request.Request(url, headers={"User-Agent": "Rexy/4.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            if not data.get("results"):
                logger.warning(f"Geocoding: no results for '{city}'")
                return None

            result = data["results"][0]
            return {
                "lat":     result["latitude"],
                "lon":     result["longitude"],
                "city":    result["name"],
                "country": result.get("country", ""),
            }
        except Exception as e:
            logger.warning(f"Geocoding failed for '{city}': {e}")
            return None

    # ── Step 2: Fetch weather from lat/lon ──
    def _fetch_weather(self, city: str) -> Dict[str, Any] | None:
        try:
            geo = self._geocode(city)
            if geo is None:
                return None

            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={geo['lat']}&longitude={geo['lon']}"
                f"&current=temperature_2m,apparent_temperature,relative_humidity_2m"
                f",wind_speed_10m,weather_code"
                f"&timezone=auto"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Rexy/4.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            current = data["current"]
            code    = int(current["weather_code"])
            emoji, desc = WEATHER_CODES.get(code, ("🌡️", "Unknown"))

            return {
                "city":       f"{geo['city']}, {geo['country']}",
                "temp_c":     round(current["temperature_2m"]),
                "feels_like": round(current["apparent_temperature"]),
                "humidity":   int(current["relative_humidity_2m"]),
                "wind_kmph":  round(current["wind_speed_10m"]),
                "desc":       desc,
                "emoji":      emoji,
            }

        except Exception as e:
            logger.warning(f"Weather fetch failed for '{city}': {e}")
            return None

    # ── Format reply ──
    def _format_reply(self, w: Dict[str, Any]) -> str:
        return (
            f"{w['emoji']} {w['city']}\n"
            f"🌡️ {w['temp_c']}°C  (feels like {w['feels_like']}°C)\n"
            f"💧 Humidity: {w['humidity']}%  |  💨 Wind: {w['wind_kmph']} km/h\n"
            f"📋 {w['desc']}"
        )