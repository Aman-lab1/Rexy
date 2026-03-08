# Phase 5: OS Boundary Layer - NO direct system calls
import logging
from typing import Dict, Any
from .registry import registry, Capability

logger = logging.getLogger(__name__)

class OSBoundary:
    def __init__(self, mode: str = "dry-run"):
        self.mode = mode  # dry-run | real
    
    def execute(self, cap_name: str, params: Dict[str, Any] = {}) -> Dict[str, Any]:
        """Execute capability through boundary"""
        cap = registry.get(cap_name)
        if not cap:
            return {"status": "error", "output": f"Capability '{cap_name}' not registered"}
        
        logger.info(f"BOUNDARY | {cap_name} | risk:{cap.risk_level} | mode:{self.mode}")
        
        if self.mode == "dry-run" or cap.dry_run:
            return self._simulate(cap, params)
        
        # FUTURE: Real execution (Phase 6+)
        return {"status": "error", "output": "Real execution not enabled"}
    
    def _simulate(self, cap: Capability, params: Dict[str, Any]) -> Dict[str, Any]:
        """Safe simulation for ALL capabilities"""
        if cap.name == "get_time":
            from datetime import datetime
            return {"status": "success", "output": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "simulated": True}
        elif cap.name == "echo":
            msg = params.get("message", "echo")
            return {"status": "success", "output": f"👋 {msg}", "simulated": True}
        elif cap.name == "list_files":
            return {"status": "success", "output": "📁 [5 files simulated: file1.txt, file2.py...]", "simulated": True}
        elif cap.name == "calculate":  # ← NOW WORKS!
            expr = params.get("expression", "1+1")
            try:
                result = eval(expr, {"__builtins__": {}})
                return {"status": "success", "output": f"🧮 {expr} = {result}", "simulated": True}
            except:
                return {"status": "error", "output": f"❌ Calc error: {expr}", "simulated": True}
        
        return {"status": "success", "output": f"✅ Would execute {cap.name}({params})", "simulated": True}

# Global boundary (dry-run default)
boundary = OSBoundary(mode="dry-run")
