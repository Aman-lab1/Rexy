"""
REXY WEATHER PLUGIN
Fetches current weather using wttr.in — completely free, no API key needed.

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

# Weather condition codes → friendly emoji + label
WEATHER_CODES = {
    113: ("☀️",  "Clear"),
    116: ("⛅",  "Partly cloudy"),
    119: ("☁️",  "Cloudy"),
    122: ("☁️",  "Overcast"),
    143: ("🌫️",  "Mist"),
    176: ("🌦️",  "Patchy rain"),
    179: ("🌨️",  "Patchy snow"),
    182: ("🌧️",  "Sleet"),
    185: ("🌧️",  "Freezing drizzle"),
    200: ("⛈️",  "Thundery outbreaks"),
    227: ("🌨️",  "Blowing snow"),
    230: ("❄️",  "Blizzard"),
    248: ("🌫️",  "Fog"),
    260: ("🌫️",  "Freezing fog"),
    263: ("🌦️",  "Light drizzle"),
    266: ("🌧️",  "Drizzle"),
    281: ("🌧️",  "Freezing drizzle"),
    284: ("🌧️",  "Heavy freezing drizzle"),
    293: ("🌦️",  "Light rain"),
    296: ("🌧️",  "Light rain"),
    299: ("🌧️",  "Moderate rain"),
    302: ("🌧️",  "Moderate rain"),
    305: ("🌧️",  "Heavy rain"),
    308: ("🌧️",  "Heavy rain"),
    311: ("🌧️",  "Light freezing rain"),
    314: ("🌧️",  "Moderate freezing rain"),
    317: ("🌧️",  "Light sleet"),
    320: ("🌨️",  "Moderate sleet"),
    323: ("🌨️",  "Light snow"),
    326: ("❄️",  "Light snow"),
    329: ("❄️",  "Moderate snow"),
    332: ("❄️",  "Moderate snow"),
    335: ("❄️",  "Heavy snow"),
    338: ("❄️",  "Heavy snow"),
    350: ("🌧️",  "Ice pellets"),
    353: ("🌦️",  "Light rain shower"),
    356: ("🌧️",  "Moderate rain shower"),
    359: ("🌧️",  "Heavy rain shower"),
    362: ("🌧️",  "Light sleet shower"),
    365: ("🌧️",  "Moderate sleet shower"),
    368: ("🌨️",  "Light snow shower"),
    371: ("❄️",  "Moderate snow shower"),
    374: ("🌧️",  "Light ice pellet shower"),
    377: ("🌧️",  "Moderate ice pellet shower"),
    386: ("⛈️",  "Thundery rain"),
    389: ("⛈️",  "Heavy thundery rain"),
    392: ("⛈️",  "Thundery snow"),
    395: ("❄️",  "Heavy snow"),
}


class WeatherPlugin(RexyPlugin):
    """Fetches weather from wttr.in for any city."""

    # ── Plugin metadata ──
    @property
    def intent_name(self) -> str:
        return "WEATHER"

    @property
    def description(self) -> str:
        return "Fetch current weather for any city using wttr.in"

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

    # ── Main execute method ──
    def execute(self, message: str, emotion: str, state: Dict[str, Any], args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Extract city from message, fetch weather, return formatted reply.
        Falls back to last known city, then asks user if no city found.
        """
        city = args.get("city", "").strip()
        if not city:
            city = self._extract_city(message)

        # No city in message → try last known city from state
        if not city:
            city = state.get("memory", {}).get("last_weather_city")

        # Still no city → ask user
        if not city:
            return {
                "reply": "🌍 Which city should I check the weather for?",
                "emotion": "neutral",
                "state": "speaking"
            }

        # Fetch weather
        weather_data = self._fetch_weather(city)

        if weather_data is None:
            return {
                "reply": f"❌ Couldn't fetch weather for '{city}'. Check the city name and try again.",
                "emotion": "neutral",
                "state": "speaking"
            }

        # Remember city for next time
        if "memory" not in state:
            state["memory"] = {}
        state["memory"]["last_weather_city"] = weather_data["city"]

        return {
            "reply": self._format_reply(weather_data),
            "emotion": "neutral",
            "state": "speaking"
        }

    # ── City extraction ──
    def _extract_city(self, message: str) -> str:
        """
        Try to pull a city name out of the message.
        Handles: "weather in X", "weather for X", "X weather", "temperature in X"
        """
        message_clean = message.strip()

        # Pattern: "weather in X" / "weather for X" / "temperature in X"
        match = re.search(
            r'\b(?:weather|temperature|temp|forecast|climate)\s+(?:in|for|at|of)\s+([A-Za-z\s]+?)(?:\?|$|\.)',
            message_clean,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        # Pattern: "X weather" / "X temperature"
        match = re.search(
            r'([A-Za-z\s]+?)\s+(?:weather|temperature|temp|forecast)',
            message_clean,
            re.IGNORECASE
        )
        if match:
            city = match.group(1).strip()
            # Filter out common non-city words
            skip = {"what", "how", "is", "the", "today", "current", "like", "s"}
            if city.lower() not in skip and len(city) > 2:
                return city

        # Pattern: "in X" at the end
        match = re.search(r'\bin\s+([A-Za-z\s]+?)(?:\?|$|\.)', message_clean, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern: "and in X?" or "in X?" short follow-ups
        match = re.search(r'^(?:and\s+)?in\s+([A-Za-z\s]+?)(?:\?|$|\.)', message_clean, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    # ── Fetch from wttr.in ──
    def _fetch_weather(self, city: str) -> Dict[str, Any] | None:
        """
        Call wttr.in JSON API. Returns parsed weather dict or None on failure.
        wttr.in is free, no API key needed.
        """
        try:
            encoded_city = urllib.parse.quote(city)
            url = f"https://wttr.in/{encoded_city}?format=j1"

            # ✅ No custom SSL context — urllib uses system certs by default (safe)
            req = urllib.request.Request(url, headers={"User-Agent": "Rexy/4.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)

            current = data["current_condition"][0]
            area    = data["nearest_area"][0]

            temp_c      = int(current["temp_C"])
            feels_like  = int(current["FeelsLikeC"])
            humidity    = int(current["humidity"])
            wind_kmph   = int(current["windspeedKmph"])
            weather_code= int(current["weatherCode"])
            desc        = current["weatherDesc"][0]["value"]
            city_name   = area["areaName"][0]["value"]
            country     = area["country"][0]["value"]

            emoji, _ = WEATHER_CODES.get(weather_code, ("🌡️", desc))

            return {
                "city":       f"{city_name}, {country}",
                "temp_c":     temp_c,
                "feels_like": feels_like,
                "humidity":   humidity,
                "wind_kmph":  wind_kmph,
                "desc":       desc,
                "emoji":      emoji,
            }

        except Exception as e:
            logger.warning(f"Weather fetch failed for '{city}': {e}")
            return None

    # ── Format reply ──
    def _format_reply(self, w: Dict[str, Any]) -> str:
        """Build a clean, readable weather reply."""
        return (
            f"{w['emoji']} {w['city']}\n"
            f"🌡️ {w['temp_c']}°C  (feels like {w['feels_like']}°C)\n"
            f"💧 Humidity: {w['humidity']}%  |  💨 Wind: {w['wind_kmph']} km/h\n"
            f"📋 {w['desc']}"
        )
