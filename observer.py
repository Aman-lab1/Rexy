# observer.py
"""
REXY OBSERVABILITY v2.0 — FLIGHT RECORDER + ANALYTICS

What changed from v1:
    - emit() works exactly the same (no breaking changes)
    - NEW: timing context manager → measure response times
    - NEW: LLM call tracking → see how many Groq calls per session
    - NEW: plugin call tracking → which plugins are actually used
    - NEW: error categorization → find what's failing
    - NEW: daily summary → one-line report of the day
    - NEW: /logs/rexy_observer.log (structured NDJSON, same as before)
    - NEW: /logs/rexy_daily.log (human-readable daily summary)

Zero behavioral impact — all logging is fire-and-forget.
Rexy never crashes because of observer failures.

Author: Aman (EEE @ Ahmedabad University)
"""

import json
import hashlib
import os
import time
import logging
from contextlib import contextmanager
from datetime import datetime, date
from typing import Any, Dict, Generator, Optional

logger = logging.getLogger("rexy.observer")

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
LOG_DIR      = "logs"
EVENT_LOG    = os.path.join(LOG_DIR, "rexy_observer.log")    # NDJSON, one event per line
DAILY_LOG    = os.path.join(LOG_DIR, "rexy_daily.log")       # Human-readable daily summary
LLM_LOG      = os.path.join(LOG_DIR, "rexy_llm_usage.log")   # LLM call tracker

os.makedirs(LOG_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# IN-MEMORY SESSION COUNTERS
# Resets when server restarts (intentional).
# For persistence, flush to Supabase daily.
# ─────────────────────────────────────────────
_session_stats: Dict[str, Any] = {
    "date":              str(date.today()),

    # LLM tracking
    "llm_calls":         0,      # total Groq calls
    "gate_hits_exact":   0,      # messages handled by exact match (no LLM)
    "gate_hits_regex":   0,      # messages handled by regex (no LLM)
    "gate_misses":       0,      # messages that needed LLM

    # Plugin tracking
    "plugin_calls":      {},     # {"WEATHER": 5, "FILE_READ": 2, ...}

    # Performance
    "total_response_ms": 0,      # sum of all response times
    "response_count":    0,      # number of responses timed
    "slowest_ms":        0,
    "fastest_ms":        float('inf'),

    # Errors
    "errors":            {},     # {"JSON_ERROR": 2, "GROQ_TIMEOUT": 1, ...}

    # Intents
    "intent_counts":     {},     # {"CHAT": 40, "WEATHER": 12, ...}
}


# ─────────────────────────────────────────────
# CORE emit() — UNCHANGED API
# Your existing calls work exactly the same.
# Just add new events from the list below.
# ─────────────────────────────────────────────

def emit(event_type: str, payload: Dict[str, Any]) -> None:
    """
    PASSIVE: One function. Append-only. Fail silently.
    Called AFTER decisions — zero control flow impact.

    Existing event types (from v1, unchanged):
        INTENT_LOCKED     - After IntentDetector
        SAFETY_CHECK      - After SafetyVerifier
        DECISION_NOTE     - REJECT/ALLOW/CLARIFY
        EXECUTION_RESULT  - After execute()
        UNCERTAINTY_FLAG  - Low confidence/reliability

    New event types (v2):
        GATE_HIT          - SmartGate matched (no LLM used)
        LLM_CALL          - Groq was called
        LLM_RESPONSE      - Groq responded (with timing)
        PLUGIN_CALLED     - A plugin ran
        PLUGIN_ERROR      - A plugin crashed
        ERROR             - Any error in the pipeline
        INPUT_REJECTED    - Message rejected (too long, rate limit)
        RESPONSE_TIMED    - Full response cycle timing
    """
    try:
        now = datetime.now()

        # ── Update in-memory stats based on event type ──
        _update_stats(event_type, payload)

        # ── Anonymize user input (never store raw text) ──
        safe_payload = dict(payload)
        if "user_message" in safe_payload:
            safe_payload["user_hash"] = _hash(safe_payload.pop("user_message"))

        # ── Append to NDJSON event log ──
        log_entry = {
            "ts":    now.isoformat(timespec="milliseconds"),
            "event": event_type,
            "data":  safe_payload,
        }
        _append(EVENT_LOG, json.dumps(log_entry))

    except Exception:
        pass   # NEVER crash Rexy


# ─────────────────────────────────────────────
# TIMING CONTEXT MANAGER
# Wraps a block of code and records how long it took.
#
# Usage:
#     with timed("full_pipeline", uid=uid):
#         result = await process_message(message, state)
# ─────────────────────────────────────────────

@contextmanager
def timed(label: str, **context: Any) -> Generator:
    """
    Context manager that measures wall-clock time of a block.
    Emits a RESPONSE_TIMED event when the block exits.

    Usage:
        with timed("full_pipeline", uid=uid, intent="WEATHER"):
            result = await process_message(message, state)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        emit("RESPONSE_TIMED", {
            "label":      label,
            "elapsed_ms": elapsed_ms,
            **context
        })
        logger.debug(f"⏱ {label}: {elapsed_ms}ms")


# ─────────────────────────────────────────────
# CONVENIENCE FUNCTIONS
# Thin wrappers around emit() for common events.
# These make the call sites in orchestrator.py cleaner.
# ─────────────────────────────────────────────

def log_llm_call(model: str = "groq", context: str = "") -> None:
    """Call before each Groq request."""
    emit("LLM_CALL", {"model": model, "context": context})


def log_llm_response(model: str = "groq", elapsed_ms: int = 0, success: bool = True) -> None:
    """Call after each Groq response."""
    emit("LLM_RESPONSE", {
        "model":      model,
        "elapsed_ms": elapsed_ms,
        "success":    success,
    })


def log_plugin(intent: str, elapsed_ms: int = 0, success: bool = True, error: str = "") -> None:
    """Call after a plugin runs."""
    emit("PLUGIN_CALLED", {
        "intent":     intent,
        "elapsed_ms": elapsed_ms,
        "success":    success,
        "error":      error[:80] if error else "",
    })


def log_error(error_type: str, message: str = "", context: Dict[str, Any] = {}) -> None:
    """Call when something goes wrong — categorised errors are easier to debug."""
    emit("ERROR", {
        "error_type": error_type,
        "message":    message[:200],
        **context
    })


# ─────────────────────────────────────────────
# STATS & REPORTING
# ─────────────────────────────────────────────

def get_stats() -> Dict[str, Any]:
    """
    Return the current in-memory session stats.
    Hit this from /gate-stats or a daily cron job.

    Example output:
    {
        "date": "2024-01-15",
        "llm_calls": 42,
        "gate_hits_exact": 80,
        "gate_hits_regex": 120,
        "gate_misses": 42,
        "gate_efficiency": "82.35%",     ← % of traffic that never touched Groq
        "groq_calls_saved": 200,
        "plugin_calls": {"WEATHER": 15, "SYSTEM_INFO": 8},
        "avg_response_ms": 340,
        "slowest_ms": 1820,
        "fastest_ms": 12,
        "errors": {"JSON_ERROR": 1},
        "intent_counts": {"CHAT": 90, "WEATHER": 15, "GET_TIME": 30}
    }
    """
    stats = dict(_session_stats)

    # Gate efficiency
    total_msgs = (
        stats["gate_hits_exact"] +
        stats["gate_hits_regex"] +
        stats["gate_misses"]
    )
    if total_msgs > 0:
        saved = stats["gate_hits_exact"] + stats["gate_hits_regex"]
        stats["gate_efficiency"]   = f"{(saved / total_msgs * 100):.2f}%"
        stats["groq_calls_saved"]  = saved
    else:
        stats["gate_efficiency"]  = "0.00%"
        stats["groq_calls_saved"] = 0

    # Average response time
    if stats["response_count"] > 0:
        stats["avg_response_ms"] = int(stats["total_response_ms"] / stats["response_count"])
    else:
        stats["avg_response_ms"] = 0

    # Clean up internal accumulators from the output
    del stats["total_response_ms"]
    del stats["response_count"]

    return stats


def write_daily_summary() -> None:
    """
    Write a human-readable daily summary to rexy_daily.log.
    Call this at midnight, or on server shutdown.
    Perfect for a cron job or APScheduler task later (Phase 2).
    """
    try:
        stats = get_stats()
        lines = [
            f"\n{'='*55}",
            f"  REXY DAILY REPORT — {stats['date']}",
            f"{'='*55}",
            f"  Messages processed : {stats.get('groq_calls_saved', 0) + stats['llm_calls']}",
            f"  Groq LLM calls     : {stats['llm_calls']}",
            f"  Groq calls SAVED   : {stats.get('groq_calls_saved', 0)}",
            f"  Gate efficiency    : {stats['gate_efficiency']}",
            f"  Avg response time  : {stats['avg_response_ms']}ms",
            f"  Slowest response   : {stats['slowest_ms']}ms",
            f"",
            f"  Plugin calls:",
        ]
        for intent, count in sorted(stats["plugin_calls"].items(), key=lambda x: -x[1]):
            lines.append(f"    {intent:<20} {count}")

        lines.append(f"")
        lines.append(f"  Top intents:")
        for intent, count in sorted(stats["intent_counts"].items(), key=lambda x: -x[1])[:8]:
            lines.append(f"    {intent:<20} {count}")

        if stats["errors"]:
            lines.append(f"")
            lines.append(f"  Errors:")
            for err_type, count in stats["errors"].items():
                lines.append(f"    {err_type:<25} {count}")
        lines.append(f"{'='*55}\n")

        summary = "\n".join(lines)
        _append(DAILY_LOG, summary)
        logger.info(f"Daily summary written to {DAILY_LOG}")

    except Exception as e:
        logger.warning(f"Daily summary failed: {e}")


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────

def _update_stats(event_type: str, payload: Dict[str, Any]) -> None:
    """Update in-memory counters. Called by emit()."""
    try:
        # Gate tracking
        if event_type == "GATE_HIT":
            reliability = payload.get("reliability", "")
            if reliability == "GATE_EXACT":
                _session_stats["gate_hits_exact"] += 1
            elif reliability == "GATE_REGEX":
                _session_stats["gate_hits_regex"] += 1

        elif event_type == "LLM_CALL":
            _session_stats["llm_calls"]    += 1
            _session_stats["gate_misses"]  += 1

        # Plugin tracking
        elif event_type in ("PLUGIN_CALLED", "EXECUTION_RESULT"):
            intent = payload.get("intent", "UNKNOWN")
            if intent:
                _session_stats["plugin_calls"][intent] = (
                    _session_stats["plugin_calls"].get(intent, 0) + 1
                )

        # Intent tracking (from INTENT_LOCKED)
        elif event_type == "INTENT_LOCKED":
            intent = payload.get("intent", "UNKNOWN")
            _session_stats["intent_counts"][intent] = (
                _session_stats["intent_counts"].get(intent, 0) + 1
            )

        # Response timing
        elif event_type == "RESPONSE_TIMED":
            ms = payload.get("elapsed_ms", 0)
            _session_stats["total_response_ms"] += ms
            _session_stats["response_count"]    += 1
            if ms > _session_stats["slowest_ms"]:
                _session_stats["slowest_ms"] = ms
            if ms < _session_stats["fastest_ms"]:
                _session_stats["fastest_ms"] = ms

        # Error tracking
        elif event_type == "ERROR":
            err_type = payload.get("error_type", "UNKNOWN")
            _session_stats["errors"][err_type] = (
                _session_stats["errors"].get(err_type, 0) + 1
            )

    except Exception:
        pass  # Stats are best-effort


def _append(filepath: str, line: str) -> None:
    """Append a line to a log file. Creates file if it doesn't exist."""
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _hash(text: str) -> str:
    """Hash sensitive text — never store raw user input."""
    if not text:
        return "EMPTY"
    return hashlib.sha256(text.encode()).hexdigest()[:8]


# ─────────────────────────────────────────────
# DEFINED EVENT TYPES
# Reference — not enforced, just documentation.
# ─────────────────────────────────────────────
EVENT_TYPES = {
    # v1 (unchanged)
    "INTENT_LOCKED",      # After IntentDetector finalises intent
    "SAFETY_CHECK",       # After SafetyVerifier runs
    "DECISION_NOTE",      # REJECT / ALLOW / CLARIFY decision
    "EXECUTION_RESULT",   # After execute() returns
    "UNCERTAINTY_FLAG",   # Low confidence / reliability

    # v2 (new)
    "GATE_HIT",           # SmartGate matched → Groq NOT called
    "LLM_CALL",           # Groq call initiated
    "LLM_RESPONSE",       # Groq responded
    "PLUGIN_CALLED",      # A plugin executed
    "ERROR",              # Any pipeline error
    "INPUT_REJECTED",     # Message blocked (too long, rate-limited)
    "RESPONSE_TIMED",     # Response cycle timing
}