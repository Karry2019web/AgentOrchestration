"""Tests for worker placement policy validation."""

import json
import pytest
from src.common.placement import (
    PlacementValidationResult,
    ValidationSeverity,
    validate_placement,
    validate_deployment_manifest,
    validate_node_selector,
    validate_tolerations,
    validate_affinity,
    WORKER_CLASS_POLICIES,
)


class TestWorkerClassPolicies:
    def test_all_classes_have_required_fields(self):
        for name, policy in WORKER_CLASS_POLICIES.items():
            assert "description" in policy, f"{name} missing description"
            assert "required_node_selector" in policy, f"{name} missing required_node_selector"
            assert "allowed_tolerations" in policy, f"{name} missing allowed_tolerations"
            assert "allowed_affinity_types" in policy, f"{name} missing allowed_affinity_types"

    def test_gpu_class_has_gpu_toleration(self):
        gpu_policy = WORKER_CLASS_POLICIES["gpu"]
        toleration_keys = [t["key"] for t in gpu_policy["allowed_tolerations"]]
        assert "nvidia.com/gpu" in toleration_keys


class TestValidateNodeSelector:
    def test_missing_node_selector_is_error(self):
        result = PlacementValidationResult()
        validate_node_selector({}, {"type": "general-purpose"}, result)
        assert not result.valid
        assert any("No node selector defined" in v.message for v in result.violations)

    def test_correct_node_selector_passes(self):
        result = PlacementValidationResult()
        validate_node_selector({"type": "gpu-optimized"}, {"type": "gpu-optimized"}, result)
        assert result.valid
        assert len(result.violations) == 0

    def test_wrong_value_is_error(self):
        result = PlacementValidationResult()
        validate_node_selector({"type": "wrong"}, {"type": "gpu-optimized"}, result)
        assert not result.valid

    def test_missing_required_key_is_error(self):
        result = PlacementValidationResult()
        validate_node_selector({"other": "val"}, {"type": "high-memory", "size": "large"}, result)
        assert not result.valid


class TestValidateTolerations:
    def test_missing_tolerations_with_policy_requirement(self):
        result = PlacementValidationResult()
        validate_tolerations([], [{"key": "nvidia.com/gpu", "operator": "Exists"}], result)
        assert result.valid
        assert any("No tolerations defined" in v.message for v in result.violations)

    def test_allowed_toleration_passes(self):
        result = PlacementValidationResult()
        validate_tolerations(
            [{"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}],
            [{"key": "nvidia.com/gpu", "operator": "Exists"}],
            result,
        )
        assert result.valid

    def test_disallowed_toleration_is_warning(self):
        result = PlacementValidationResult()
        validate_tolerations(
            [{"key": "bad-key", "operator": "Exists"}],
            [{"key": "allowed", "operator": "Exists"}],
            result,
        )
        assert result.valid
        assert any("bad-key" in v.message for v in result.violations)


class TestValidateAffinity:
    def test_no_affinity_skips_validation(self):
        result = PlacementValidationResult()
        validate_affinity(None, ["required"], result)
        assert result.valid
        assert len(result.violations) == 0

    def test_node_affinity_allowed_for_required_class(self):
        result = PlacementValidationResult()
        validate_affinity(
            {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {}}},
            ["required", "preferred"],
            result,
        )
        assert result.valid


class TestValidatePlacement:
    def test_unknown_worker_class(self):
        manifest = {"nodeSelector": {"type": "general-purpose"}}
        result = validate_placement("nonexistent", manifest)
        assert not result.valid
        assert any("Unknown worker class" in v.message for v in result.violations)

    def test_default_class_valid_manifest(self):
        manifest = {"nodeSelector": {"type": "general-purpose"}}
        result = validate_placement("default", manifest)
        assert result.valid

    def test_default_class_missing_selector(self):
        manifest = {}
        result = validate_placement("default", manifest)
        assert not result.valid
        assert result.deployment_summary != ""

    def test_gpu_class_valid_manifest(self):
        manifest = {
            "nodeSelector": {"type": "gpu-optimized"},
            "tolerations": [{"key": "nvidia.com/gpu", "operator": "Exists"}],
        }
        result = validate_placement("gpu", manifest)
        assert result.valid

    def test_gpu_class_missing_gpu_toleration(self):
        manifest = {"nodeSelector": {"type": "gpu-optimized"}}
        result = validate_placement("gpu", manifest)
        assert result.valid
        assert any("No tolerations defined" in v.message for v in result.violations)

    def test_isolated_class_requires_dedicated_selector(self):
        manifest = {"nodeSelector": {"type": "general-purpose"}}
        result = validate_placement("isolated", manifest)
        assert not result.valid
        assert any("dedicated" in v.message for v in result.violations)

    def test_deployment_summary_is_set(self):
        manifest = {"nodeSelector": {"type": "general-purpose"}}
        result = validate_placement("default", manifest)
        assert "worker_class=default" in result.deployment_summary
        assert "node_selector_keys=" in result.deployment_summary
        assert "toleration_count=" in result.deployment_summary
        assert "has_affinity=" in result.deployment_summary


class TestValidateDeploymentManifest:
    def test_valid_dict_manifest(self):
        manifest = {"workerClass": "gpu", "nodeSelector": {"type": "gpu-optimized"}}
        result = validate_deployment_manifest(manifest)
        assert result.valid

    def test_worker_class_default_when_missing(self):
        manifest = {"nodeSelector": {"type": "general-purpose"}}
        result = validate_deployment_manifest(manifest)
        assert result.valid
        assert result.worker_class == "default"

    def test_to_dict_serializable(self):
        manifest = {"nodeSelector": {"type": "general-purpose"}}
        result = validate_deployment_manifest(manifest)
        d = result.to_dict()
        assert "valid" in d
        assert "worker_class" in d
        assert "deployment_summary" in d
        assert "violations" in d
        json.dumps(d)


class TestPlacementValidationResult:
    def test_add_violation_error_sets_invalid(self):
        r = PlacementValidationResult()
        r.add_violation("test", "error msg", ValidationSeverity.ERROR)
        assert not r.valid

    def test_add_violation_warning_keeps_valid(self):
        r = PlacementValidationResult()
        r.add_violation("test", "warning msg", ValidationSeverity.WARNING)
        assert r.valid

    def test_to_dict_contains_all_fields(self):
        r = PlacementValidationResult(worker_class="gpu", deployment_summary="test summary")
        r.add_violation("node_selector", "missing key", ValidationSeverity.ERROR, actual=None, expected="val")
        d = r.to_dict()
        assert d["valid"] is False
        assert d["worker_class"] == "gpu"
        assert d["deployment_summary"] == "test summary"
        assert len(d["violations"]) == 1
        v = d["violations"][0]
        assert v["field"] == "node_selector"
        assert v["severity"] == "error"
