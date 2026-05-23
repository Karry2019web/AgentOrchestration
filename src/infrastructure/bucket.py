"""Storage bucket provisioning validator.

Validates new and existing storage buckets against a security baseline
that covers encryption, public access blocks, versioning, and lifecycle
policies. Prevents weaker defaults from being provisioned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class BaselineStatus(Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    ERROR = "error"


@dataclass
class EncryptionSettings:
    enabled: bool = True
    algorithm: str = "AES256"
    key_source: str = "SSE-S3"


@dataclass
class PublicAccessBlock:
    block_public_acls: bool = True
    block_public_policy: bool = True
    ignore_public_acls: bool = True
    restrict_public_buckets: bool = True


@dataclass
class VersioningPolicy:
    enabled: bool = True
    mfa_delete: bool = False


@dataclass
class LifecycleRule:
    id: str
    enabled: bool = True
    expiration_days: Optional[int] = None
    noncurrent_version_expiration_days: Optional[int] = None
    transition_to_glacier_days: Optional[int] = None
    abort_incomplete_multipart_upload_days: int = 7


@dataclass
class LifecyclePolicy:
    rules: List[LifecycleRule] = field(default_factory=lambda: [
        LifecycleRule(id="expire-noncurrent-versions", noncurrent_version_expiration_days=90),
        LifecycleRule(id="abort-incomplete-uploads", abort_incomplete_multipart_upload_days=7),
    ])


@dataclass
class BaselinePolicy:
    encryption: EncryptionSettings = field(default_factory=EncryptionSettings)
    public_access_block: PublicAccessBlock = field(default_factory=PublicAccessBlock)
    versioning: VersioningPolicy = field(default_factory=VersioningPolicy)
    lifecycle: LifecyclePolicy = field(default_factory=LifecyclePolicy)

    def to_dict(self) -> dict:
        return {
            "encryption": asdict(self.encryption),
            "public_access_block": asdict(self.public_access_block),
            "versioning": asdict(self.versioning),
            "lifecycle": asdict(self.lifecycle),
        }


@dataclass
class BucketConfig:
    name: str
    encryption: Optional[Dict] = None
    public_access_block: Optional[Dict] = None
    versioning: Optional[Dict] = None
    lifecycle: Optional[Dict] = None

    @classmethod
    def from_dict(cls, data: dict) -> "BucketConfig":
        return cls(
            name=data.get("name", ""),
            encryption=data.get("encryption"),
            public_access_block=data.get("public_access_block"),
            versioning=data.get("versioning"),
            lifecycle=data.get("lifecycle"),
        )


@dataclass
class ValidationResult:
    check: str
    status: BaselineStatus
    message: str
    details: Optional[Dict] = None


class BucketValidator:
    def __init__(self, baseline: Optional[BaselinePolicy] = None):
        self.baseline = baseline or BaselinePolicy()

    def validate(self, config: BucketConfig) -> List[ValidationResult]:
        results: List[ValidationResult] = []
        results.append(self._check_encryption(config))
        results.append(self._check_public_access_block(config))
        results.append(self._check_versioning(config))
        results.extend(self._check_lifecycle(config))
        return results

    def is_compliant(self, config: BucketConfig) -> bool:
        return all(r.status == BaselineStatus.COMPLIANT for r in self.validate(config))

    def _check_encryption(self, config: BucketConfig) -> ValidationResult:
        baseline = self.baseline.encryption
        actual = config.encryption or {}
        if not actual.get("enabled", False):
            return ValidationResult(
                check="encryption", status=BaselineStatus.NON_COMPLIANT,
                message=f"Bucket encryption is disabled. Baseline requires enabled={baseline.enabled}.",
                details={"expected": asdict(baseline), "actual": actual},
            )
        if actual.get("algorithm", "").upper() != baseline.algorithm:
            return ValidationResult(
                check="encryption.algorithm", status=BaselineStatus.NON_COMPLIANT,
                message=f"Expected encryption algorithm {baseline.algorithm}, got {actual.get('algorithm')}.",
                details={"expected": baseline.algorithm, "actual": actual.get("algorithm")},
            )
        return ValidationResult(check="encryption", status=BaselineStatus.COMPLIANT,
                                message="Encryption settings meet baseline requirements.")

    def _check_public_access_block(self, config: BucketConfig) -> ValidationResult:
        baseline = self.baseline.public_access_block
        actual = config.public_access_block or {}
        violations: List[str] = []
        for field_name in ("block_public_acls", "block_public_policy",
                           "ignore_public_acls", "restrict_public_buckets"):
            expected = getattr(baseline, field_name)
            actual_val = actual.get(field_name, None)
            if actual_val is None or actual_val != expected:
                violations.append(f"{field_name}: expected {expected}, got {actual_val}")
        if violations:
            return ValidationResult(check="public_access_block", status=BaselineStatus.NON_COMPLIANT,
                                    message="Public access block settings deviate from baseline.",
                                    details={"violations": violations})
        return ValidationResult(check="public_access_block", status=BaselineStatus.COMPLIANT,
                                message="All public access blocks are correctly configured.")

    def _check_versioning(self, config: BucketConfig) -> ValidationResult:
        baseline = self.baseline.versioning
        actual = config.versioning or {}
        if not actual.get("enabled", False):
            return ValidationResult(check="versioning", status=BaselineStatus.NON_COMPLIANT,
                                    message=f"Bucket versioning not enabled. Baseline requires enabled={baseline.enabled}.",
                                    details={"expected": asdict(baseline), "actual": actual})
        return ValidationResult(check="versioning", status=BaselineStatus.COMPLIANT,
                                message="Versioning is enabled per baseline.")

    def _check_lifecycle(self, config: BucketConfig) -> List[ValidationResult]:
        results: List[ValidationResult] = []
        baseline_rules = self.baseline.lifecycle.rules
        actual_rules = config.lifecycle.get("rules", []) if config.lifecycle else []
        if not actual_rules:
            results.append(ValidationResult(check="lifecycle.rules_present", status=BaselineStatus.NON_COMPLIANT,
                                            message="No lifecycle rules configured.",
                                            details={"expected_count": len(baseline_rules), "actual_count": 0}))
            return results
        for baseline_rule in baseline_rules:
            match = self._find_matching_rule(baseline_rule, actual_rules)
            if match is None:
                results.append(ValidationResult(check=f"lifecycle.rule.{baseline_rule.id}",
                                                status=BaselineStatus.NON_COMPLIANT,
                                                message=f"Required lifecycle rule '{baseline_rule.id}' is missing.",
                                                details={"rule": asdict(baseline_rule)}))
            else:
                results.append(ValidationResult(check=f"lifecycle.rule.{baseline_rule.id}",
                                                status=BaselineStatus.COMPLIANT,
                                                message=f"Lifecycle rule '{baseline_rule.id}' present."))
        return results

    @staticmethod
    def _find_matching_rule(baseline_rule: LifecycleRule, actual_rules: List[Dict]) -> Optional[Dict]:
        for rule in actual_rules:
            if rule.get("id", "") == baseline_rule.id:
                return rule
        return None


def validate_bucket_baseline(config: dict) -> Tuple[bool, List[dict]]:
    validator = BucketValidator()
    bucket_config = BucketConfig.from_dict(config)
    results = validator.validate(bucket_config)
    compliant = all(r.status == BaselineStatus.COMPLIANT for r in results)
    return compliant, [{"check": r.check, "status": r.status.value, "message": r.message, "details": r.details} for r in results]


@dataclass
class RemediationStep:
    check: str
    action: str
    priority: str


def generate_migration_plan(config: BucketConfig, baseline: Optional[BaselinePolicy] = None) -> List[RemediationStep]:
    validator = BucketValidator(baseline)
    results = validator.validate(config)
    plan: List[RemediationStep] = []
    for r in results:
        if r.status != BaselineStatus.NON_COMPLIANT:
            continue
        if r.check == "encryption":
            plan.append(RemediationStep(check="encryption", action="Enable default encryption (AES256) on the bucket.", priority="high"))
        elif r.check == "public_access_block":
            plan.append(RemediationStep(check="public_access_block", action="Apply BlockPublicAccess settings.", priority="high"))
        elif r.check == "versioning":
            plan.append(RemediationStep(check="versioning", action="Enable bucket versioning.", priority="high"))
        elif "lifecycle" in r.check:
            plan.append(RemediationStep(check=r.check, action="Add missing lifecycle rules.", priority="medium"))
    return plan
