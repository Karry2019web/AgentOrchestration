"""Deployment placement policy validator — node selector, toleration, and affinity validation."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


VALID_TOLERATION_OPERATORS: Set[str] = {"Exists", "Equal"}
VALID_TOLERATION_EFFECTS: Set[str] = {"NoSchedule", "PreferNoSchedule", "NoExecute"}
VALID_AFFINITY_TYPES: Set[str] = {"nodeAffinity", "podAffinity", "podAntiAffinity"}

VALID_NODE_SELECTOR_VALUES: Dict[str, List[str]] = {
    "kubernetes.io/os": ["linux", "windows"],
    "kubernetes.io/arch": ["amd64", "arm64"],
}

WORKLOAD_CLASSES: Dict[str, Dict[str, Any]] = {
    "worker.processor": {
        "allowed_node_selector_keys": {"kubernetes.io/os", "kubernetes.io/arch"},
        "require_tolerations": True,
        "allow_affinity": True,
    },
    "worker.analyzer": {
        "allowed_node_selector_keys": {"kubernetes.io/os", "kubernetes.io/arch", "accelerator"},
        "require_tolerations": True,
        "allow_affinity": True,
    },
    "worker.extractor": {
        "allowed_node_selector_keys": {"kubernetes.io/os", "kubernetes.io/arch"},
        "require_tolerations": False,
        "allow_affinity": False,
    },
    "worker.sink": {
        "allowed_node_selector_keys": {"kubernetes.io/os", "kubernetes.io/arch"},
        "require_tolerations": False,
        "allow_affinity": False,
    },
    "monitor.watcher": {
        "allowed_node_selector_keys": {"kubernetes.io/os", "kubernetes.io/arch"},
        "require_tolerations": False,
        "allow_affinity": False,
    },
}


class PlacementValidationError(Exception):
    """Raised when a deployment manifest fails placement policy validation."""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class Toleration:
    """A pod toleration for a node taint."""
    key: str = ""
    operator: str = "Equal"
    value: str = ""
    effect: str = "NoSchedule"

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Toleration":
        return Toleration(
            key=data.get("key", ""),
            operator=data.get("operator", "Equal"),
            value=data.get("value", ""),
            effect=data.get("effect", "NoSchedule"),
        )


@dataclass
class PlacementPolicy:
    """Parsed placement policy from a deployment manifest."""
    node_selector: Dict[str, str] = field(default_factory=dict)
    tolerations: List[Toleration] = field(default_factory=list)
    affinity: Optional[Dict[str, Any]] = None
    workload_class: str = ""

    @classmethod
    def from_manifest(cls, data: Dict[str, Any]) -> "PlacementPolicy":
        placement = data.get("placement", data.get("spec", {}).get("placement", {}))
        return cls(
            node_selector=placement.get("nodeSelector", {}),
            tolerations=[Toleration.from_dict(t) for t in placement.get("tolerations", [])],
            affinity=placement.get("affinity"),
            workload_class=data.get("workload_class", data.get("type", "")),
        )


class PlacementValidator:
    """Validates placement policy against documented policies."""
    def __init__(self, policy: PlacementPolicy):
        self.policy = policy
        self.errors: List[str] = []

    def validate(self) -> None:
        self.errors = []
        self._validate_node_selector_keys()
        self._validate_node_selector_values()
        self._validate_tolerations()
        self._validate_affinity()
        self._validate_workload_class_policy()
        if self.errors:
            raise PlacementValidationError(self.errors)

    def _validate_node_selector_keys(self) -> None:
        for key, val in self.policy.node_selector.items():
            if not key.strip():
                self.errors.append("Node selector key must not be empty")
            if not val.strip():
                self.errors.append(f"Node selector value for '{key}' must not be empty")

    def _validate_node_selector_values(self) -> None:
        for key, val in self.policy.node_selector.items():
            known_values = VALID_NODE_SELECTOR_VALUES.get(key)
            if known_values and val not in known_values:
                self.errors.append(
                    f"Node selector '{key}' has invalid value '{val}'. "
                    f"Allowed: {', '.join(known_values)}"
                )

    def _validate_tolerations(self) -> None:
        for i, tol in enumerate(self.policy.tolerations):
            if not tol.key.strip():
                self.errors.append(f"Toleration #{i + 1} has empty key")
            if tol.operator not in VALID_TOLERATION_OPERATORS:
                self.errors.append(
                    f"Toleration '{tol.key}' has invalid operator '{tol.operator}'. "
                    f"Allowed: {', '.join(VALID_TOLERATION_OPERATORS)}"
                )
            if tol.operator == "Equal" and not tol.value:
                self.errors.append(
                    f"Toleration '{tol.key}' with operator 'Equal' requires a non-empty value"
                )
            if tol.effect not in VALID_TOLERATION_EFFECTS:
                self.errors.append(
                    f"Toleration '{tol.key}' has invalid effect '{tol.effect}'. "
                    f"Allowed: {', '.join(VALID_TOLERATION_EFFECTS)}"
                )

    def _validate_affinity(self) -> None:
        if self.policy.affinity is None:
            return
        if not isinstance(self.policy.affinity, dict):
            self.errors.append("Affinity must be a dictionary")
            return
        for key in self.policy.affinity:
            if key not in VALID_AFFINITY_TYPES:
                self.errors.append(
                    f"Unknown affinity type '{key}'. "
                    f"Allowed: {', '.join(VALID_AFFINITY_TYPES)}"
                )

    def _validate_workload_class_policy(self) -> None:
        wc = self.policy.workload_class
        if not wc:
            return
        policy = WORKLOAD_CLASSES.get(wc)
        if policy is None:
            self.errors.append(f"Unknown workload class '{wc}'")
            return
        allowed_keys = policy["allowed_node_selector_keys"]
        for key in self.policy.node_selector:
            if key not in allowed_keys:
                self.errors.append(
                    f"Node selector key '{key}' is not allowed for workload class '{wc}'"
                )
        if policy["require_tolerations"] and not self.policy.tolerations:
            self.errors.append(f"Workload class '{wc}' requires at least one toleration")
        if not policy["allow_affinity"] and self.policy.affinity:
            self.errors.append(f"Affinity is not allowed for workload class '{wc}'")


def validate_manifest(data: Dict[str, Any]) -> List[str]:
    policy = PlacementPolicy.from_manifest(data)
    validator = PlacementValidator(policy)
    try:
        validator.validate()
        return []
    except PlacementValidationError as e:
        return e.errors


def format_validation_summary(data: Dict[str, Any]) -> str:
    policy = PlacementPolicy.from_manifest(data)
    parts = [f"Workload Class: {policy.workload_class or 'unspecified'}"]
    if policy.node_selector:
        selectors = [f"{k}={v}" for k, v in policy.node_selector.items()]
        parts.append(f"Node Selectors: {', '.join(selectors)}")
    else:
        parts.append("Node Selectors: none (default scheduling)")
    if policy.tolerations:
        tols = [f"{t.key}:{t.effect}" for t in policy.tolerations]
        parts.append(f"Tolerations: {len(policy.tolerations)} ({', '.join(tols)})")
    else:
        parts.append("Tolerations: none")
    if policy.affinity:
        affinity_types = list(policy.affinity.keys())
        parts.append(f"Affinity: {', '.join(affinity_types)}")
    else:
        parts.append("Affinity: none")
    errors = validate_manifest(data)
    if errors:
        parts.append(f"Validation: FAILED ({len(errors)} issue(s))")
    else:
        parts.append("Validation: PASSED")
    return "\n".join(parts)
