"""Tests for deployment placement policy validator."""

import pytest
from src.deploy.placement import (
    PlacementValidator,
    PlacementPolicy,
    PlacementValidationError,
    Toleration,
    validate_manifest,
    format_validation_summary,
)


class TestPlacementValidator:
    """Placement policy validation test suite."""

    def test_empty_node_selector_key(self):
        policy = PlacementPolicy(node_selector={"": "linux"}, workload_class="worker.processor")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "empty" in str(exc.value).lower()

    def test_empty_node_selector_value(self):
        policy = PlacementPolicy(node_selector={"kubernetes.io/os": ""}, workload_class="worker.processor")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "empty" in str(exc.value).lower()

    def test_valid_node_selector(self):
        policy = PlacementPolicy(node_selector={"kubernetes.io/os": "linux"}, workload_class="worker.processor")
        validator = PlacementValidator(policy)
        validator.validate()

    def test_invalid_node_selector_value(self):
        policy = PlacementPolicy(node_selector={"kubernetes.io/os": "darwin"}, workload_class="worker.processor")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "darwin" in str(exc.value)
        assert "linux" in str(exc.value)

    def test_toleration_empty_key(self):
        policy = PlacementPolicy(
            tolerations=[Toleration(key="", operator="Exists", effect="NoSchedule")],
            workload_class="worker.processor",
        )
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "empty key" in str(exc.value).lower()

    def test_toleration_invalid_operator(self):
        policy = PlacementPolicy(
            tolerations=[Toleration(key="gpu", operator="InvalidOp", effect="NoSchedule")],
        )
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "invalid operator" in str(exc.value).lower()

    def test_toleration_equal_requires_value(self):
        policy = PlacementPolicy(
            tolerations=[Toleration(key="gpu", operator="Equal", value="", effect="NoSchedule")],
        )
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "non-empty value" in str(exc.value).lower()

    def test_toleration_invalid_effect(self):
        policy = PlacementPolicy(
            tolerations=[Toleration(key="gpu", operator="Exists", effect="InvalidEffect")],
        )
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "invalid effect" in str(exc.value).lower()

    def test_valid_toleration(self):
        policy = PlacementPolicy(
            tolerations=[Toleration(key="gpu", operator="Equal", value="nvidia", effect="NoSchedule")],
            workload_class="worker.processor",
        )
        validator = PlacementValidator(policy)
        validator.validate()

    def test_unknown_affinity_type(self):
        policy = PlacementPolicy(affinity={"unknownAffinity": {}}, workload_class="worker.analyzer")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "unknown affinity" in str(exc.value).lower()

    def test_valid_affinity(self):
        policy = PlacementPolicy(
            affinity={"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": []}}},
            workload_class="worker.analyzer",
        )
        validator = PlacementValidator(policy)
        validator.validate()

    def test_unknown_workload_class(self):
        policy = PlacementPolicy(node_selector={"kubernetes.io/os": "linux"}, workload_class="unknown.class")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "unknown workload class" in str(exc.value).lower()

    def test_workload_class_requires_tolerations(self):
        policy = PlacementPolicy(node_selector={"kubernetes.io/os": "linux"}, workload_class="worker.analyzer")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "requires at least one toleration" in str(exc.value).lower()

    def test_workload_class_disallows_affinity(self):
        policy = PlacementPolicy(
            node_selector={"kubernetes.io/os": "linux"},
            workload_class="worker.sink",
            affinity={"nodeAffinity": {}},
        )
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "affinity is not allowed" in str(exc.value).lower()

    def test_workload_class_restricted_node_selector(self):
        policy = PlacementPolicy(node_selector={"accelerator": "nvidia"}, workload_class="worker.sink")
        validator = PlacementValidator(policy)
        with pytest.raises(PlacementValidationError) as exc:
            validator.validate()
        assert "not allowed" in str(exc.value).lower()

    def test_validate_manifest_valid(self):
        manifest = {"name": "test", "type": "worker.processor", "placement": {
            "nodeSelector": {"kubernetes.io/os": "linux"},
            "tolerations": [{"key": "dedicated", "operator": "Equal", "value": "ml", "effect": "NoSchedule"}],
        }}
        assert validate_manifest(manifest) == []

    def test_validate_manifest_multiple_errors(self):
        manifest = {"name": "bad", "type": "worker.sink", "placement": {
            "nodeSelector": {"accelerator": "nvidia"},
            "affinity": {"nodeAffinity": {}},
        }}
        errors = validate_manifest(manifest)
        assert len(errors) >= 2

    def test_empty_manifest_valid(self):
        assert validate_manifest({}) == []

    def test_placement_from_spec(self):
        manifest = {"name": "test", "workload_class": "worker.processor", "spec": {
            "placement": {"nodeSelector": {"kubernetes.io/os": "linux"}, "tolerations": [
                {"key": "gpu", "operator": "Equal", "value": "nvidia", "effect": "NoSchedule"}
            ]},
        }}
        assert validate_manifest(manifest) == []

    def test_missing_selector_ok(self):
        policy = PlacementPolicy(workload_class="worker.sink")
        validator = PlacementValidator(policy)
        validator.validate()

    def test_toleration_exists_no_value_ok(self):
        policy = PlacementPolicy(
            tolerations=[Toleration(key="gpu", operator="Exists", effect="NoSchedule")],
            workload_class="worker.processor",
        )
        validator = PlacementValidator(policy)
        validator.validate()

    def test_format_summary_contains_fields(self):
        manifest = {"name": "test", "type": "worker.processor", "placement": {
            "nodeSelector": {"kubernetes.io/os": "linux"},
        }}
        summary = format_validation_summary(manifest)
        assert "Workload Class" in summary
        assert "Node Selectors" in summary
        assert "Tolerations" in summary
        assert "Affinity" in summary
        assert "Validation" in summary
