"""Tests for storage bucket provisioning validation."""

import pytest
from src.infrastructure.bucket import (
    BaselinePolicy,
    BucketConfig,
    BucketValidator,
    BaselineStatus,
    validate_bucket_baseline,
    generate_migration_plan,
    EncryptionSettings,
)


class TestBaselinePolicyDefaults:
    def test_encryption_default(self):
        baseline = BaselinePolicy()
        assert baseline.encryption.enabled is True
        assert baseline.encryption.algorithm == "AES256"

    def test_public_access_block_default(self):
        baseline = BaselinePolicy()
        assert baseline.public_access_block.block_public_acls is True
        assert baseline.public_access_block.block_public_policy is True
        assert baseline.public_access_block.ignore_public_acls is True
        assert baseline.public_access_block.restrict_public_buckets is True

    def test_versioning_default(self):
        baseline = BaselinePolicy()
        assert baseline.versioning.enabled is True

    def test_lifecycle_default(self):
        baseline = BaselinePolicy()
        assert len(baseline.lifecycle.rules) >= 1


class TestBucketValidator:
    def test_compliant_bucket_passes(self):
        config = BucketConfig(
            name="logs-bucket",
            encryption={"enabled": True, "algorithm": "AES256"},
            public_access_block={
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True,
            },
            versioning={"enabled": True},
            lifecycle={"rules": [
                {"id": "expire-noncurrent-versions", "noncurrent_version_expiration_days": 90},
                {"id": "abort-incomplete-uploads", "abort_incomplete_multipart_upload_days": 7},
            ]},
        )
        validator = BucketValidator()
        assert all(r.status == BaselineStatus.COMPLIANT for r in validator.validate(config))
        assert validator.is_compliant(config) is True

    def test_missing_encryption_fails(self):
        config = BucketConfig(name="insecure-bucket", encryption={"enabled": False})
        validator = BucketValidator()
        enc_results = [r for r in validator.validate(config) if "encryption" in r.check]
        assert any(r.status == BaselineStatus.NON_COMPLIANT for r in enc_results)

    def test_no_encryption_config_fails(self):
        config = BucketConfig(name="no-encryption-bucket")
        assert BucketValidator().is_compliant(config) is False

    def test_missing_public_access_block_fails(self):
        config = BucketConfig(
            name="public-bucket",
            encryption={"enabled": True, "algorithm": "AES256"},
            versioning={"enabled": True},
            lifecycle={"rules": [{"id": "expire-noncurrent-versions"}, {"id": "abort-incomplete-uploads"}]},
        )
        assert BucketValidator().is_compliant(config) is False

    def test_partial_public_access_block_fails(self):
        config = BucketConfig(
            name="partial-block-bucket",
            encryption={"enabled": True, "algorithm": "AES256"},
            public_access_block={
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": False, "restrict_public_buckets": True,
            },
            versioning={"enabled": True},
            lifecycle={"rules": [{"id": "expire-noncurrent-versions"}, {"id": "abort-incomplete-uploads"}]},
        )
        assert BucketValidator().is_compliant(config) is False

    def test_disabled_versioning_fails(self):
        config = BucketConfig(
            name="no-versioning-bucket",
            encryption={"enabled": True, "algorithm": "AES256"},
            public_access_block={
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True,
            },
            versioning={"enabled": False},
            lifecycle={"rules": [{"id": "expire-noncurrent-versions"}, {"id": "abort-incomplete-uploads"}]},
        )
        assert BucketValidator().is_compliant(config) is False

    def test_missing_lifecycle_rules_fails(self):
        config = BucketConfig(
            name="no-lifecycle-bucket",
            encryption={"enabled": True, "algorithm": "AES256"},
            public_access_block={
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True,
            },
            versioning={"enabled": True},
        )
        assert BucketValidator().is_compliant(config) is False


class TestValidateBucketBaseline:
    def test_compliant_config(self):
        compliant, results = validate_bucket_baseline({
            "name": "test-bucket",
            "encryption": {"enabled": True, "algorithm": "AES256"},
            "public_access_block": {
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True,
            },
            "versioning": {"enabled": True},
            "lifecycle": {"rules": [
                {"id": "expire-noncurrent-versions", "noncurrent_version_expiration_days": 90},
                {"id": "abort-incomplete-uploads", "abort_incomplete_multipart_upload_days": 7},
            ]},
        })
        assert compliant is True

    def test_non_compliant_config(self):
        compliant, results = validate_bucket_baseline({"name": "insecure-bucket", "encryption": {"enabled": False}})
        assert compliant is False
        assert any(r["status"] == "non_compliant" for r in results)


class TestMigrationPlan:
    def test_generates_remediation_steps(self):
        config = BucketConfig(name="legacy-bucket", encryption={"enabled": False})
        plan = generate_migration_plan(config)
        assert len(plan) > 0
        assert any(s.check == "encryption" for s in plan)

    def test_no_steps_for_compliant_bucket(self):
        config = BucketConfig(
            name="good-bucket",
            encryption={"enabled": True, "algorithm": "AES256"},
            public_access_block={
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True,
            },
            versioning={"enabled": True},
            lifecycle={"rules": [{"id": "expire-noncurrent-versions"}, {"id": "abort-incomplete-uploads"}]},
        )
        plan = generate_migration_plan(config)
        assert len(plan) == 0


class TestCustomBaseline:
    def test_stronger_encryption(self):
        baseline = BaselinePolicy(
            encryption=EncryptionSettings(enabled=True, algorithm="AES256", key_source="SSE-KMS"),
        )
        config = BucketConfig(
            name="kms-bucket",
            encryption={"enabled": True, "algorithm": "AES256", "key_source": "SSE-KMS"},
            public_access_block={
                "block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True,
            },
            versioning={"enabled": True},
            lifecycle={"rules": [{"id": "expire-noncurrent-versions"}, {"id": "abort-incomplete-uploads"}]},
        )
        validator = BucketValidator(baseline)
        assert validator.is_compliant(config) is True
