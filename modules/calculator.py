"""
REXY CALCULATOR MODULE v4.0
Handles all math — activation mode and chain mode.

Two modes:
  Activation mode: triggered by "calc" / "calculate" keyword
  Chain mode: when calculator mode is already active, no keyword needed
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("rexy.calculator")

# Natural language → math operator mapping
NATURAL_LANG_OPS = {
    "divide by":   "/",
    "divided by":  "/",
    "divide":      "/",
    "multiply by": "*",
    "multiplied by": "*",
    "multiply":    "*",
    "times":       "*",
    "plus":        "+",
    "add":         "+",
    "minus":       "-",
    "subtract":    "-",
}


class CalculatorHandler:
    """
    Processes calculator input in two modes:

    1. Activation mode — user says "calc 10+5" or "calculate 50*2"
       → Strip the keyword, extract expression, evaluate.

    2. Chain mode — calculator mode already active (state["intent"]["mode"] == "calculator")
       and no calc keyword present.
       → If math expression found: evaluate standalone.
       → If natural language operator + number found: apply to last_result.
       → If neither: exit calculator mode gracefully.
    """

    def process(self, message: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point. Figures out which mode applies and handles accordingly.
        Returns: {"reply", "mode", "last_result", "state"}
        """
        message_lower = message.lower().strip()
        has_calc_keyword = bool(re.search(r'\b(calc|calculate)\b', message_lower))
        in_chain_mode    = state["intent"].get("mode") == "calculator"

        # ── ACTIVATION MODE ──
        # "calc" or "calculate" keyword present → always fresh activation
        if has_calc_keyword:
            return self._activation_mode(message_lower, state)

        # ── CHAIN MODE ──
        # Already in calculator mode, no keyword
        if in_chain_mode:
            return self._chain_mode(message_lower, state)

        # ── FALLBACK (shouldn't normally reach here) ──
        return {
            "reply":       "🧮 Say 'calc <expression>' to start! e.g. 'calc 10+5'",
            "mode":        "chat",
            "last_result": None,
            "state":       "speaking"
        }

    # ─────────────────────────────────────────────
    # ACTIVATION MODE
    # ─────────────────────────────────────────────
    def _activation_mode(self, message: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle "calc ..." or "calculate ...".
        Strips the keyword, extracts and evaluates the math expression.
        """
        # Strip calc/calculate keyword
        cleaned = re.sub(r'\b(calculate|calc)\b\s*', '', message).strip()

        # Normalize natural language operators first
        cleaned = self._normalize_ops(cleaned)

        # Extract math expression
        expr = self._extract_expression(cleaned)

        if expr is None:
            # Keyword present but no expression found → enter calc mode waiting
            state["intent"]["mode"] = "calculator"
            return {
                "reply":       "🧮 Calculator ON! Give me an expression: e.g. '20*3', 'divide by 5'",
                "mode":        "calculator",
                "last_result": state["intent"].get("last_result"),
                "state":       "thinking"
            }

        result = self._safe_eval(expr)
        if result is None:
            return {
                "reply":       f"❌ Couldn't parse '{expr}'. Try something like 'calc 10+5'.",
                "mode":        "calculator",
                "last_result": state["intent"].get("last_result"),
                "state":       "speaking"
            }

        state["intent"]["mode"]        = "calculator"
        state["intent"]["last_result"] = float(result)
        return {
            "reply":       f"🧮 {expr} = {self._format_result(result)}",
            "mode":        "calculator",
            "last_result": float(result),
            "state":       "thinking"
        }

    # ─────────────────────────────────────────────
    # CHAIN MODE
    # ─────────────────────────────────────────────
    def _chain_mode(self, message: str, state: Dict[str, Any]) -> Dict[str, Any]:
        last_result = state["intent"].get("last_result")
        normalized  = self._normalize_ops(message)

        # ── Case B FIRST: operator + number applied to last_result ──
        # Must run BEFORE Case A, otherwise "*10" gets parsed as just "10"
        if last_result is not None:
            op_match = re.search(r'([\+\-\*\/])\s*(\d+\.?\d*)', normalized)
            if op_match:
                op      = op_match.group(1)
                operand = float(op_match.group(2))
                try:
                    result = eval(f"{last_result} {op} {operand}")
                    state["intent"]["last_result"] = float(result)
                    op_display = {'*': '×', '/': '÷', '+': '+', '-': '−'}.get(op, op)
                    return {
                        "reply":       f"🧮 {self._format_result(last_result)} {op_display} {operand} = {self._format_result(result)}",
                        "mode":        "calculator",
                        "last_result": float(result),
                        "state":       "thinking"
                    }
                except Exception:
                    pass

        # ── Case A: Standalone math expression ──
        expr = self._extract_expression(normalized)
        if expr:
            result = self._safe_eval(expr)
            if result is not None:
                state["intent"]["last_result"] = float(result)
                return {
                    "reply":       f"🧮 {expr} = {self._format_result(result)}",
                    "mode":        "calculator",
                    "last_result": float(result),
                    "state":       "thinking"
                }

        # ── Case C: Not math → exit ──
        state["intent"]["mode"]        = "chat"
        state["intent"]["last_result"] = None
        return {
            "reply":       "🧮 Calculator off. What else can I help with?",
            "mode":        "chat",
            "last_result": None,
            "state":       "speaking"
        }

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────
    def _normalize_ops(self, text: str) -> str:
        """Replace natural language math words with symbols."""
        for phrase, symbol in NATURAL_LANG_OPS.items():
            # Use word boundary to avoid partial replacements
            text = re.sub(rf'\b{re.escape(phrase)}\b', symbol, text)
        return text

    def _extract_expression(self, text: str) -> Optional[str]:
        """
        Find a math expression in the text.
        Returns the expression string or None.
        """
        # Look for: digits, operators, spaces, parentheses, decimals
        match = re.search(r'\d[\d\s\+\-\*\/\(\)\.]*\d', text)
        if match:
            return match.group().strip()
        # Single number (e.g. just "42")
        single = re.match(r'^\s*(\d+\.?\d*)\s*$', text)
        if single:
            return single.group(1)
        return None

    def _safe_eval(self, expr: str) -> Optional[float]:
        """
        Evaluate a math expression ONLY if it passes the safe character check.
        Never passes untrusted strings to eval.
        """
        expr = expr.strip()
        # Only allow digits, operators, spaces, parens, decimal points
        if not re.fullmatch(r'[0-9\.\+\-\*\/\(\)\s]+', expr):
            logger.warning(f"Unsafe expression rejected: '{expr}'")
            return None
        try:
            result = eval(expr)  # Safe because of fullmatch guard above
            return float(result)
        except Exception as e:
            logger.debug(f"Eval failed for '{expr}': {e}")
            return None

    def _try_chain_op(self, text: str, last_result: float):
        """
        Try to extract a natural language operation to apply to last_result.
        Returns (op_symbol, operand, result) or None.
        """
        op_map = {
            r'\*': ('×', '*'),
            r'\/': ('÷', '/'),
            r'\+': ('+', '+'),
            r'\-': ('−', '-'),
        }
        numbers = re.findall(r'\d+\.?\d*', text)
        if not numbers:
            return None

        # Check which operator appears in the normalized text
        for pattern, (display, actual) in op_map.items():
            if re.search(pattern, text):
                operand = float(numbers[0])
                try:
                    result = eval(f"{last_result} {actual} {operand}")
                    return (display, operand, float(result))
                except Exception:
                    return None
        return None

    def _format_result(self, value: float) -> str:
        """
        Format result nicely:
        - Show as int if it's a whole number (10.0 → "10")
        - Show 4 decimal places otherwise ("3.1416")
        """
        if value == int(value):
            return str(int(value))
        return f"{value:.4f}".rstrip('0').rstrip('.')
