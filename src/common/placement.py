"""Worker Placement Policy — Validates node selectors, tolerations, and affinity settings."""

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationSeverity(Enum):
    """Severity of a placement policy violation."""
    ERROR = "error"
    WARNING = "warning"


@dataclass
class PlacementViolation:
    """A single violation of the placement policy."""
    field: str
    message: str
    severity: ValidationSeverity
    actual: Any = None
    expected: Any = None


@dataclass
class PlacementValidationResult:
    """Result of validating a worker manifest's placement policy."""
    valid: bool = True
    violations: List[PlacementViolation] = field(default_factory=list)
    worker_class: str = ""
    deployment_summary: str = ""

    def add_violation(self, field: str, message: str,
                      severity: ValidationSeverity = ValidationSeverity.ERROR,
                      actual: Any = None, expected: Any = None) -> None:
        self.violations.append(PlacementViolation(
            field=field, message=message, severity=severity,
            actual=actual, expected=expected,
        ))
        if severity == ValidationSeverity.ERROR:
            self.valid = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "worker_class": self.worker_class,
            "deployment_summary": self.deployment_summary,
            "violations": [asdict(v) for v in self.violations],
        }


# Standard worker class definitions with their required placement policies
WORKER_CLASS_POLICIES: Dict[str, Dict[str, Any]] = {
    "default": {
        "description": "General-purpose worker with no special isolation requirements",
        "required_node_selector": {"type": "general-purpose"},
        "allowed_tolerations": [],
        "allowed_affinity_types": ["preferred"],
    },
    "gpu": {
        "description": "GPU-accelerated worker requiring node with GPU capacity",
        "required_node_selector": {"type": "gpu-optimized"},
        "allowed_tolerations": [
            {"key": "nvidia.com/gpu", "operator": "Exists"},
        ],
        "allowed_affinity_types": ["required", "preferred"],
    },
    "high-memory": {
        "description": "Memory-intensive worker requiring high-memory nodes",
        "required_node_selector": {"type": "high-memory", "size": "large"},
        "allowed_tolerations": [],
        "allowed_affinity_types": ["required"],
    },
    "isolated": {
        "description": "Isolated worker with strict node affinity and no-sharing tolerations",
        "required_node_selector": {"type": "dedicated", "environment": "isolated"},
        "allowed_tolerations": [
            {"key": "dedicated", "operator": "Exists"},
        ],
        "allowed_affinity_types": ["required"],
    },
    "spot": {
        "description": "Cost-optimized worker tolerant of spot instance eviction",
        "required_node_selector": {"type": "spot", "lifecycle": "ec2spot"},
        "allowed_tolerations": [
            {"key": "spot", "operator": "Exists"},
        ],
        "allowed_affinity_types": ["preferred"],
    },
}


def _get_policy(worker_class: str) -> Optional[Dict[str, Any]]:
    """Get the placement policy for a worker class."""
    return WORKER_CLASS_POLICIES.get(worker_class)


def validate_node_selector(
    manifest_node_selector: Dict[str, str],
    policy_node_selector: Dict[str, str],
    result: PlacementValidationResult,
) -> None:
    """Validate that the manifest's node selector meets policy requirements."""
    if not manifest_node_selector:
        result.add_violation(
            field="node_selector",
            message="No node selector defined in deployment manifest. "
                    f"Policy requires at least: {policy_node_selector}",
            severity=ValidationSeverity.ERROR,
            actual=None,
            expected=policy_node_selector,
        )
        return

    for key, expected_value in policy_node_selector.items():
        actual_value = manifest_node_selector.get(key)
        if actual_value is None:
            result.add_violation(
                field=f"node_selector.{key}",
                message=f"Node selector key '{key}' is missing. "
                        f"Expected value '{expected_value}' according to worker class policy.",
                severity=ValidationSeverity.ERROR,
                actual=None,
                expected=expected_value,
            )
        elif actual_value != expected_value:
            result.add_violation(
                field=f"node_selector.{key}",
                message=f"Node selector '{key}' has value '{actual_value}', "
                        f"but policy expects '{expected_value}'.",
                severity=ValidationSeverity.ERROR,
                actual=actual_value,
                expected=expected_value,
            )


def validate_tolerations(
    manifest_tolerations: List[Dict[str, Any]],
    allowed_tolerations: List[Dict[str, Any]],
    result: PlacementValidationResult,
) -> None:
    """Validate that the manifest's tolerations are within policy boundaries."""
    if not manifest_tolerations and allowed_tolerations:
        result.add_violation(
            field="tolerations",
            message="No tolerations defined, but the worker class policy requires "
                    "specific tolerations for correct node placement.",
            severity=ValidationSeverity.WARNING,
            actual=None,
            expected=allowed_tolerations,
        )
        return

    for tol in (manifest_tolerations or []):
        key = tol.get("key", "")
        op = tol.get("operator", "Equal")
        allowed = False
        for policy_tol in allowed_tolerations:
            if policy_tol.get("key") == key and policy_tol.get("operator") == op:
                allowed = True
                break
        if not allowed:
            result.add_violation(
                field="tolerations",
                message=f"Toleration key='{key}', operator='{op}' is not in the "
                        f"allowed set for this worker class.",
                severity=ValidationSeverity.WARNING,
                actual={"key": key, "operator": op},
                expected=allowed_tolerations,
            )


def validate_affinity(
    manifest_affinity: Optional[Dict[str, Any]],
    allowed_affinity_types: List[str],
    result: PlacementValidationResult,
) -> None:
    """Validate that the affinity settings are appropriate for the worker class."""
    if not manifest_affinity:
        return

    if "nodeAffinity" in manifest_affinity:
        if "required" not in allowed_affinity_types and            "preferred" not in allowed_affinity_types:
            result.add_violation(
                field="affinity.nodeAffinity",
                message="Node affinity is set but not allowed for this worker class.",
                severity=ValidationSeverity.WARNING,
                actual="nodeAffinity present",
                expected="no nodeAffinity",
            )

    if "podAntiAffinity" in manifest_affinity and        "preferred" not in allowed_affinity_types:
        result.add_violation(
            field="affinity.podAntiAffinity",
            message="Pod anti-affinity is set but the worker class does not "
                    "support it.",
            severity=ValidationSeverity.WARNING,
            actual="podAntiAffinity present",
            expected=f"one of {allowed_affinity_types}",
        )


def validate_placement(
    worker_class: str,
    manifest: Dict[str, Any],
) -> PlacementValidationResult:
    """Validate a deployment manifest against the worker class placement policy."""
    result = PlacementValidationResult()
    result.worker_class = worker_class

    policy = _get_policy(worker_class)
    if not policy:
        result.add_violation(
            field="worker_class",
            message=f"Unknown worker class '{worker_class}'. "
                    f"Available classes: {list(WORKER_CLASS_POLICIES.keys())}",
            severity=ValidationSeverity.ERROR,
            actual=worker_class,
            expected=list(WORKER_CLASS_POLICIES.keys()),
        )
        return result

    manifest_node_selector = manifest.get("nodeSelector", {}) or {}
    validate_node_selector(manifest_node_selector, policy["required_node_selector"], result)

    manifest_tolerations = manifest.get("tolerations", []) or []
    validate_tolerations(manifest_tolerations, policy["allowed_tolerations"], result)

    manifest_affinity = manifest.get("affinity", None)
    validate_affinity(manifest_affinity, policy["allowed_affinity_types"], result)

    result.deployment_summary = (
        f"worker_class={worker_class}, "
        f"node_selector_keys={list(manifest_node_selector.keys())}, "
        f"toleration_count={len(manifest_tolerations)}, "
        f"has_affinity={'yes' if manifest_affinity else 'no'}"
    )

    return result


def validate_deployment_manifest(manifest_path_or_dict: Any) -> PlacementValidationResult:
    """Top-level entry point: validate a deployment manifest by path or dict."""
    if isinstance(manifest_path_or_dict, str):
        import json as _json
        with open(manifest_path_or_dict) as _f:
            manifest = _json.load(_f)
    else:
        manifest = manifest_path_or_dict

    worker_class = manifest.get("workerClass", manifest.get("worker_class", "default"))
    return validate_placement(worker_class, manifest)
