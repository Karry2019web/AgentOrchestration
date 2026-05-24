"""Data classification registry — defines data classes and approved destinations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class DataClass(Enum):
    """Classification labels for operational data."""
    OPERATIONAL = "operational"
    ANALYTICAL = "analytical"
    FINANCIAL = "financial"
    PII = "pii"
    SECURITY = "security"
    AUDIT = "audit"


@dataclass(frozen=True)
class DestinationPolicy:
    """Policy binding a destination to allowable data classes."""
    destination: str
    allowed_classes: Set[DataClass]
    require_purpose: bool = True
    max_retention_days: Optional[int] = None


DEFAULT_POLICIES: Dict[str, DestinationPolicy] = {
    "analytics_store": DestinationPolicy(
        destination="analytics_store",
        allowed_classes={DataClass.ANALYTICAL, DataClass.OPERATIONAL},
        max_retention_days=365,
    ),
    "compliance_lake": DestinationPolicy(
        destination="compliance_lake",
        allowed_classes={DataClass.AUDIT, DataClass.FINANCIAL},
        max_retention_days=2555,
    ),
    "operational_log": DestinationPolicy(
        destination="operational_log",
        allowed_classes={DataClass.OPERATIONAL, DataClass.SECURITY},
        max_retention_days=90,
    ),
    "analytics_warehouse": DestinationPolicy(
        destination="analytics_warehouse",
        allowed_classes={DataClass.ANALYTICAL, DataClass.FINANCIAL, DataClass.OPERATIONAL},
        max_retention_days=730,
    ),
}


class DataClassificationRegistry:
    """Registry enforcing data class to destination policy validation."""

    def __init__(self, policies: Optional[Dict[str, DestinationPolicy]] = None):
        self._policies: Dict[str, DestinationPolicy] = dict(policies or DEFAULT_POLICIES)

    def register_policy(self, policy: DestinationPolicy) -> None:
        self._policies[policy.destination] = policy

    def get_policy(self, destination: str) -> Optional[DestinationPolicy]:
        return self._policies.get(destination)

    def is_destination_allowed(self, destination: str, data_class: DataClass) -> bool:
        policy = self._policies.get(destination)
        if policy is None:
            return False
        return data_class in policy.allowed_classes

    def list_destinations_for_class(self, data_class: DataClass) -> List[str]:
        return [
            dest for dest, policy in self._policies.items()
            if data_class in policy.allowed_classes
        ]

    @property
    def known_destinations(self) -> Set[str]:
        return set(self._policies.keys())
