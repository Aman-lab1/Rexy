# Phase 5: Single source of truth for capabilities
import yaml
import logging
from typing import Dict, Any
from pydantic import BaseModel
from enum import Enum

logger = logging.getLogger(__name__)

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Capability(BaseModel):
    name: str
    description: str
    risk_level: RiskLevel
    params_schema: Dict[str, Any] = {}
    dry_run: bool = True  # Default simulation
    handler: str = ""  # "os_boundary.get_time"

class CapabilityRegistry:
    def __init__(self):
        self.capabilities: Dict[str, Capability] = {}
        self.load_from_yaml()
    
    def load_from_yaml(self):
        """Load capabilities from config/capabilities.yaml"""
        try:
            with open("config/capabilities.yaml", "r") as f:
                data = yaml.safe_load(f)
                for cap_data in data.get("capabilities", []):
                    cap = Capability(**cap_data)
                    self.capabilities[cap.name] = cap
                logger.info(f"🔥 LOADED {len(self.capabilities)} CAPABILITIES")
        except FileNotFoundError:
            logger.warning("config/capabilities.yaml missing - using empty registry")
    
    def get(self, name: str) -> Capability | None:
        return self.capabilities.get(name.lower())
    
    def list_all(self) -> list:
        return list(self.capabilities.values())

# Global singleton
registry = CapabilityRegistry()
