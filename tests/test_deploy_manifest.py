import pytest
from src.deploy.manifest import (
    ArchitectureDigest,
    ManifestValidationError,
    ManifestValidator,
    MultiArchManifest,
    ReleaseSummary,
    ScanStatus,
    ValidationStatus,
)


class TestArchitectureDigest:
    def test_is_valid_all_passed(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc123",
            test_status=ValidationStatus.PASSED,
            scan_status=ScanStatus.PASSED,
            validated_at=1000.0,
        )
        assert arch.is_valid() is True

    def test_is_valid_scan_not_required(self):
        arch = ArchitectureDigest(
            architecture="arm64",
            digest="sha256:def456",
            test_status=ValidationStatus.PASSED,
            scan_status=ScanStatus.NOT_REQUIRED,
        )
        assert arch.is_valid() is True

    def test_is_valid_pending_tests(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc123",
            test_status=ValidationStatus.PENDING,
            scan_status=ScanStatus.PASSED,
        )
        assert arch.is_valid() is False

    def test_is_valid_failed_tests(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc123",
            test_status=ValidationStatus.FAILED,
            scan_status=ScanStatus.PASSED,
        )
        assert arch.is_valid() is False

    def test_is_valid_failed_scan(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc123",
            test_status=ValidationStatus.PASSED,
            scan_status=ScanStatus.FAILED,
        )
        assert arch.is_valid() is False

    def test_is_valid_skipped_tests(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc123",
            test_status=ValidationStatus.SKIPPED,
            scan_status=ScanStatus.PASSED,
        )
        assert arch.is_valid() is False

    def test_to_dict(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc123",
            test_status=ValidationStatus.PASSED,
            scan_status=ScanStatus.PASSED,
            error_message=None,
            validated_at=1000.0,
        )
        d = arch.to_dict()
        assert d["architecture"] == "amd64"
        assert d["digest"] == "sha256:abc123"
        assert d["test_status"] == "passed"
        assert d["scan_status"] == "passed"
        assert d["error_message"] is None


class TestMultiArchManifest:
    def test_register_architecture(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        entry = manifest.register_architecture("amd64", "sha256:abc123")
        assert entry.architecture == "amd64"
        assert entry.digest == "sha256:abc123"
        assert entry.test_status == ValidationStatus.PENDING

    def test_register_multiple_architectures(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.register_architecture("arm64", "sha256:def")
        assert len(manifest.architectures) == 2

    def test_record_validation(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        arch = manifest.architectures[0]
        assert arch.test_status == ValidationStatus.PASSED
        assert arch.validated_at is not None

    def test_record_validation_unregistered_raises(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        with pytest.raises(ValueError, match="not registered"):
            manifest.record_validation("amd64", ValidationStatus.PASSED)

    def test_record_scan(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_scan("arm64", ScanStatus.PASSED)
        arch = manifest.architectures[0]
        assert arch.scan_status == ScanStatus.PASSED

    def test_record_scan_with_error(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_scan("arm64", ScanStatus.FAILED, error_message="CVE-2025-1234")
        arch = manifest.architectures[0]
        assert arch.scan_status == ScanStatus.FAILED
        assert arch.error_message == "CVE-2025-1234"

    def test_is_release_ready_all_pass(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_validation("arm64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        manifest.record_scan("arm64", ScanStatus.PASSED)
        assert manifest.is_release_ready() is True

    def test_is_release_ready_one_missing(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        # arm64 not validated yet
        assert manifest.is_release_ready() is False

    def test_is_release_ready_no_architectures(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        assert manifest.is_release_ready() is False

    def test_get_validation_state(self):
        manifest = MultiArchManifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        state = manifest.get_validation_state()
        assert "amd64" in state
        assert state["amd64"].digest == "sha256:abc"


class TestManifestValidator:
    def test_create_manifest(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        assert manifest.image_name == "myapp"
        assert manifest.tag == "v1.0"

    def test_get_manifest(self):
        validator = ManifestValidator()
        validator.create_manifest("myapp", "v1.0")
        manifest = validator.get_manifest("myapp", "v1.0")
        assert manifest is not None
        assert manifest.image_name == "myapp"

    def test_get_manifest_not_found(self):
        validator = ManifestValidator()
        assert validator.get_manifest("nonexistent", "v1.0") is None

    def test_prepare_release_allows_push_when_ready(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_validation("arm64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        manifest.record_scan("arm64", ScanStatus.PASSED)

        summary = validator.prepare_release(manifest)
        assert summary.manifest_push_allowed is True
        assert summary.blocked_reason is None
        assert len(summary.architectures) == 2

    def test_prepare_release_blocks_on_missing_architecture(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        # arm64 still PENDING

        summary = validator.prepare_release(manifest)
        assert summary.manifest_push_allowed is False
        assert summary.blocked_reason is not None
        assert "incomplete validation coverage" in summary.blocked_reason
        assert "arm64" in summary.blocked_reason

    def test_prepare_release_blocks_on_failed_tests(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.record_validation("amd64", ValidationStatus.FAILED,
                                    error_message="Integration test failed")
        manifest.record_scan("amd64", ScanStatus.PASSED)

        summary = validator.prepare_release(manifest)
        assert summary.manifest_push_allowed is False
        assert "validation failures" in summary.blocked_reason
        assert "Integration test failed" in summary.blocked_reason

    def test_prepare_release_blocks_on_failed_scan(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.FAILED,
                              error_message="CVE-2025-9999")

        summary = validator.prepare_release(manifest)
        assert summary.manifest_push_allowed is False
        assert "validation failures" in summary.blocked_reason
        assert "CVE-2025-9999" in summary.blocked_reason

    def test_prepare_release_allows_with_scan_not_required(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.NOT_REQUIRED)

        summary = validator.prepare_release(manifest)
        assert summary.manifest_push_allowed is True
        assert summary.blocked_reason is None

    def test_prepare_release_raises_on_empty_manifest(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        with pytest.raises(ManifestValidationError, match="No architectures registered"):
            validator.prepare_release(manifest)

    def test_prepare_release_skipped_tests_block(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.record_validation("amd64", ValidationStatus.SKIPPED)
        manifest.record_scan("amd64", ScanStatus.PASSED)

        summary = validator.prepare_release(manifest)
        assert summary.manifest_push_allowed is False
        # SKIPPED is not FAILED, so it falls through to missing check
        assert summary.blocked_reason is not None

    def test_release_summary_to_dict(self):
        arch = ArchitectureDigest(
            architecture="amd64",
            digest="sha256:abc",
            test_status=ValidationStatus.PASSED,
            scan_status=ScanStatus.PASSED,
        )
        summary = ReleaseSummary(
            architectures=[arch],
            manifest_push_allowed=True,
            blocked_reason=None,
        )
        d = summary.to_dict()
        assert d["manifest_push_allowed"] is True
        assert d["blocked_reason"] is None
        assert len(d["architectures"]) == 1
        assert d["architectures"][0]["architecture"] == "amd64"

    def test_generate_release_report_allowed(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc123def456")
        manifest.register_architecture("arm64", "sha256:def456ghi789")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_validation("arm64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        manifest.record_scan("arm64", ScanStatus.NOT_REQUIRED)

        report = validator.generate_release_report(manifest)
        assert "myapp:v1.0" in report
        assert "ALLOWED" in report
        assert "amd64" in report
        assert "arm64" in report

    def test_generate_release_report_blocked(self):
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc")
        manifest.register_architecture("arm64", "sha256:def")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        # arm64 not done

        report = validator.generate_release_report(manifest)
        assert "BLOCKED" in report
        assert "arm64" in report


class TestEdgeCases:
    def test_multiple_validators_independent(self):
        v1 = ManifestValidator()
        v2 = ManifestValidator()
        m1 = v1.create_manifest("app1", "v1")
        m2 = v2.create_manifest("app2", "v1")
        assert v1.get_manifest("app2", "v1") is None
        assert v2.get_manifest("app1", "v1") is None

    def test_same_tag_different_images(self):
        validator = ManifestValidator()
        m1 = validator.create_manifest("frontend", "latest")
        m2 = validator.create_manifest("backend", "latest")
        m1.register_architecture("amd64", "sha256:abc")
        m2.register_architecture("arm64", "sha256:def")
        assert m1.architectures[0].architecture == "amd64"
        assert m2.architectures[0].architecture == "arm64"

    def test_reregister_same_architecture_overwrites(self):
        manifest = MultiArchManifest("myapp", "v1")
        manifest.register_architecture("amd64", "sha256:old")
        manifest.register_architecture("amd64", "sha256:new")
        assert len(manifest.architectures) == 1
        assert manifest.architectures[0].digest == "sha256:new"

    def test_validation_resets_on_reregister(self):
        manifest = MultiArchManifest("myapp", "v1")
        manifest.register_architecture("amd64", "sha256:old")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        # Re-register resets status
        manifest.register_architecture("amd64", "sha256:new")
        assert manifest.architectures[0].test_status == ValidationStatus.PENDING
        assert manifest.architectures[0].scan_status == ScanStatus.PENDING
