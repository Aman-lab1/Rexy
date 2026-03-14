"""
REXY CALCULATOR MODULE v4.1
Handles all math — activation mode and chain mode.

Two modes:
  Activation mode: triggered by "calc" / "calculate" keyword
  Chain mode: when calculator mode is already active, no keyword needed

v4.1 change: replaced eval() with AST-based safe evaluator.
"""

import re
import ast
import operator
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("rexy.calculator")

# Natural language → math operator mapping
NATURAL_LANG_OPS = {
    "divide by":     "/",
    "divided by":    "/",
    "divide":        "/",
    "multiply by":   "*",
    "multiplied by": "*",
    "multiply":      "*",
    "times":         "*",
    "plus":          "+",
    "add":           "+",
    "minus":         "-",
    "subtract":      "-",
}

# ─────────────────────────────────────────────
# AST-BASED SAFE EVALUATOR
# Replaces eval() entirely. Only allows pure arithmetic.
# If the expression contains ANYTHING else (imports, calls,
# attribute access, strings) → raises ValueError immediately.
# ─────────────────────────────────────────────

# Whitelist: only these AST node types are allowed
ALLOWED_OPERATORS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod:      operator.mod,
    ast.Pow:      operator.pow,
    ast.USub:     operator.neg,   # unary minus: -5
    ast.UAdd:     operator.pos,   # unary plus: +5
}


def _ast_eval(node):
    """
    Recursively evaluate an AST node.
    Only handles numbers and whitelisted math operators.
    Anything else raises ValueError — no exceptions.
    
    Called internally by safe_eval(). Don't call directly.
    """
    # A plain number (int or float)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Non-numeric constant: {node.value!r}")

    # Binary operation: left OP right (e.g. 5 + 3)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in ALLOWED_OPERATORS:
            raise ValueError(f"Operator not allowed: {op_type.__name__}")
        left  = _ast_eval(node.left)
        right = _ast_eval(node.right)
        # Catch division by zero here with a clear message
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ZeroDivisionError("Division by zero")
        return ALLOWED_OPERATORS[op_type](left, right)

    # Unary operation: -5 or +5
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in ALLOWED_OPERATORS:
            raise ValueError(f"Unary operator not allowed: {op_type.__name__}")
        return ALLOWED_OPERATORS[op_type](_ast_eval(node.operand))

    # Parenthesized expression — just unwrap it
    if isinstance(node, ast.Expression):
        return _ast_eval(node.body)

    # ANYTHING else (function calls, names, attributes, etc.) → blocked
    raise ValueError(f"Expression type not allowed: {type(node).__name__}")


def safe_eval(expr: str) -> float:
    """
    Safely evaluate a math expression string using AST.
    
    ✅ Allows:  "10+5", "100/4", "(3+2)*8", "2**10", "10%3"
    ❌ Blocks:  __import__, os.system, lambda, any function call
    
    Raises:
        ValueError       — for non-math expressions or unsafe content
        ZeroDivisionError — for x/0
    """
    expr = expr.strip()

    if not expr:
        raise ValueError("Empty expression.")
    if len(expr) > 200:
        raise ValueError("Expression too long (max 200 characters).")

    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError as e:
        raise ValueError(f"Invalid syntax: {e}")

    return _ast_eval(tree)


# ─────────────────────────────────────────────
# CALCULATOR HANDLER
# ─────────────────────────────────────────────

class CalculatorHandler:
    """
    Processes calculator input in two modes:

    1. Activation mode — user says "calc 10+5" or "calculate 50*2"
    2. Chain mode — calculator mode active, applying operations to last_result
    """

    def process(self, message: str, state: Dict[str, Any]) -> Dict[str, Any]:
        message_lower = message.lower().strip()
        has_calc_keyword = bool(re.search(r'\b(calc|calculate)\b', message_lower))
        in_chain_mode    = state["intent"].get("mode") == "calculator"

        if has_calc_keyword:
            return self._activation_mode(message_lower, state)

        if in_chain_mode:
            return self._chain_mode(message_lower, state)

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
        cleaned = re.sub(r'\b(calculate|calc)\b\s*', '', message).strip()
        cleaned = self._normalize_ops(cleaned)
        expr    = self._extract_expression(cleaned)

        if expr is None:
            state["intent"]["mode"] = "calculator"
            return {
                "reply":       "🧮 Calculator ON! Give me an expression: e.g. '20*3', 'divide by 5'",
                "mode":        "calculator",
                "last_result": state["intent"].get("last_result"),
                "state":       "thinking"
            }

        result = self._safe_eval_wrapped(expr)
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
        if last_result is not None:
            op_match = re.search(r'([\+\-\*\/])\s*(\d+\.?\d*)', normalized)
            if op_match:
                op      = op_match.group(1)
                operand = float(op_match.group(2))
                # ✅ Build expression string and use safe_eval — no raw eval()
                expr_str = f"{last_result} {op} {operand}"
                try:
                    result = safe_eval(expr_str)
                    state["intent"]["last_result"] = float(result)
                    op_display = {'*': '×', '/': '÷', '+': '+', '-': '−'}.get(op, op)
                    return {
                        "reply":       f"🧮 {self._format_result(last_result)} {op_display} {operand} = {self._format_result(result)}",
                        "mode":        "calculator",
                        "last_result": float(result),
                        "state":       "thinking"
                    }
                except (ValueError, ZeroDivisionError) as e:
                    return {
                        "reply":       f"❌ Math error: {str(e)}",
                        "mode":        "calculator",
                        "last_result": last_result,
                        "state":       "speaking"
                    }

        # ── Case A: Standalone math expression ──
        expr = self._extract_expression(normalized)
        if expr:
            result = self._safe_eval_wrapped(expr)
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
        for phrase, symbol in NATURAL_LANG_OPS.items():
            text = re.sub(rf'\b{re.escape(phrase)}\b', symbol, text)
        return text

    def _extract_expression(self, text: str) -> Optional[str]:
        match = re.search(r'\d[\d\s\+\-\*\/\(\)\.]*\d', text)
        if match:
            return match.group().strip()
        single = re.match(r'^\s*(\d+\.?\d*)\s*$', text)
        if single:
            return single.group(1)
        return None

    def _safe_eval_wrapped(self, expr: str) -> Optional[float]:
        """
        Wrapper around safe_eval() that returns None on failure
        (instead of raising) so callers don't need try/except everywhere.
        """
        try:
            return safe_eval(expr)
        except ZeroDivisionError:
            logger.debug(f"Division by zero in: '{expr}'")
            return None
        except ValueError as e:
            logger.debug(f"safe_eval rejected '{expr}': {e}")
            return None

    def _format_result(self, value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.4f}".rstrip('0').rstrip('.')