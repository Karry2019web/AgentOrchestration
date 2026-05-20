"""Multi-architecture Docker image manifest validation for releases.

Validates that each architecture-specific digest has passed tests and
security scan gates before allowing the combined manifest to be pushed.
"""

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class ValidationStatus(Enum):
    """Status of per-architecture validation."""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScanStatus(Enum):
    """Status of security scan gates."""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


@dataclass
class ArchitectureDigest:
    """Validation state for a single architecture's container digest."""
    architecture: str
    digest: str
    test_status: ValidationStatus = ValidationStatus.PENDING
    scan_status: ScanStatus = ScanStatus.PENDING
    error_message: Optional[str] = None
    validated_at: Optional[float] = None

    def is_valid(self) -> bool:
        """Check if this architecture digest has passed all gates."""
        if self.test_status != ValidationStatus.PASSED:
            return False
        if self.scan_status not in (ScanStatus.PASSED, ScanStatus.NOT_REQUIRED):
            return False
        return True

    def to_dict(self) -> Dict:
        return {
            "architecture": self.architecture,
            "digest": self.digest,
            "test_status": self.test_status.value,
            "scan_status": self.scan_status.value,
            "error_message": self.error_message,
            "validated_at": self.validated_at,
        }


@dataclass
class ReleaseSummary:
    """Summary of a release validation run."""
    architectures: List[ArchitectureDigest] = field(default_factory=list)
    manifest_push_allowed: bool = False
    blocked_reason: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "architectures": [a.to_dict() for a in self.architectures],
            "manifest_push_allowed": self.manifest_push_allowed,
            "blocked_reason": self.blocked_reason,
            "created_at": self.created_at,
        }


class ManifestValidationError(Exception):
    """Raised when manifest validation fails."""
    pass


class MultiArchManifest:
    """Tracks per-architecture validation state for a multi-arch image release."""

    def __init__(self, image_name: str, tag: str):
        self.image_name = image_name
        self.tag = tag
        self._architectures: Dict[str, ArchitectureDigest] = {}

    @property
    def architectures(self) -> List[ArchitectureDigest]:
        return list(self._architectures.values())

    def register_architecture(self, architecture: str, digest: str) -> ArchitectureDigest:
        """Register an architecture digest for validation.

        Args:
            architecture: Target architecture (e.g. amd64, arm64).
            digest: Container image digest (sha256:...).

        Returns:
            The ArchitectureDigest object for this architecture.
        """
        entry = ArchitectureDigest(
            architecture=architecture,
            digest=digest,
        )
        self._architectures[architecture] = entry
        return entry

    def record_validation(self, architecture: str, status: ValidationStatus,
                          error_message: Optional[str] = None) -> None:
        """Record test validation result for an architecture.

        Args:
            architecture: Architecture to update.
            status: PASSED, FAILED, or SKIPPED.
            error_message: Optional error detail on failure.

        Raises:
            ValueError: If architecture is not registered.
        """
        if architecture not in self._architectures:
            raise ValueError(f"Architecture '{architecture}' is not registered. "
                             f"Registered: {list(self._architectures.keys())}")
        entry = self._architectures[architecture]
        entry.test_status = status
        entry.validated_at = time.time()
        if error_message:
            entry.error_message = error_message

    def record_scan(self, architecture: str, status: ScanStatus,
                    error_message: Optional[str] = None) -> None:
        """Record security scan result for an architecture.

        Args:
            architecture: Architecture to update.
            status: PASSED, FAILED, or NOT_REQUIRED.
            error_message: Optional error detail on failure.

        Raises:
            ValueError: If architecture is not registered.
        """
        if architecture not in self._architectures:
            raise ValueError(f"Architecture '{architecture}' is not registered. "
                             f"Registered: {list(self._architectures.keys())}")
        entry = self._architectures[architecture]
        entry.scan_status = status
        entry.validated_at = time.time()
        if error_message:
            entry.error_message = error_message

    def is_release_ready(self) -> bool:
        """Check if all architectures have passed validation gates.

        Returns True only when every registered architecture has:
        - test_status == PASSED
        - scan_status in (PASSED, NOT_REQUIRED)
        """
        if not self._architectures:
            return False
        return all(entry.is_valid() for entry in self._architectures.values())

    def get_validation_state(self) -> Dict[str, ArchitectureDigest]:
        """Get a snapshot of all architecture validation states."""
        return dict(self._architectures)


class ManifestValidator:
    """Orchestrates manifest validation and enforces release gates.

    Usage:
        validator = ManifestValidator()
        manifest = validator.create_manifest("myapp", "v1.0")
        manifest.register_architecture("amd64", "sha256:abc...")
        manifest.register_architecture("arm64", "sha256:def...")
        manifest.record_validation("amd64", ValidationStatus.PASSED)
        manifest.record_scan("amd64", ScanStatus.PASSED)
        summary = validator.prepare_release(manifest)
        if not summary.manifest_push_allowed:
            print(f"Blocked: {summary.blocked_reason}")
    """

    def __init__(self):
        self._manifests: Dict[str, MultiArchManifest] = {}

    def create_manifest(self, image_name: str, tag: str) -> MultiArchManifest:
        """Create a new multi-arch manifest for tracking.

        Args:
            image_name: Image repository name (e.g. myapp).
            tag: Image tag (e.g. v1.0, latest).

        Returns:
            A new MultiArchManifest instance.
        """
        key = f"{image_name}:{tag}"
        manifest = MultiArchManifest(image_name, tag)
        self._manifests[key] = manifest
        return manifest

    def get_manifest(self, image_name: str, tag: str) -> Optional[MultiArchManifest]:
        """Get an existing manifest by image name and tag."""
        return self._manifests.get(f"{image_name}:{tag}")

    def prepare_release(self, manifest: MultiArchManifest) -> ReleaseSummary:
        """Check if the manifest is ready for push and produce a release summary.

        This is the main release gate: it validates all architectures and
        blocks the manifest push if any architecture has incomplete validation.

        Args:
            manifest: The MultiArchManifest to validate.

        Returns:
            A ReleaseSummary with the validation result.
        """
        self._validate_not_empty(manifest)
        failed = self._find_failed(manifest)
        blocked_reason = None

        if failed:
            blocked_reason = self._format_failed(failed)
        else:
            missing = self._find_missing_validation(manifest)
            if missing:
                blocked_reason = self._format_missing(manifest, missing)
            else:
                self._validate_full_coverage(manifest)

        summary = ReleaseSummary(
            architectures=manifest.architectures,
            manifest_push_allowed=blocked_reason is None and manifest.is_release_ready(),
            blocked_reason=blocked_reason,
        )
        return summary

    def generate_release_report(self, manifest: MultiArchManifest) -> str:
        """Generate a human-readable release summary.

        Args:
            manifest: The manifest to report on.

        Returns:
            A multi-line string summary.
        """
        lines = [
            f"## Release Report: {manifest.image_name}:{manifest.tag}",
            "",
        ]
        for arch in manifest.architectures:
            icons = {
                ValidationStatus.PASSED: "\u2705",
                ValidationStatus.FAILED: "\u274c",
                ValidationStatus.PENDING: "\u23f3",
                ValidationStatus.SKIPPED: "\u23ed\ufe0f",
            }
            scan_icons = {
                ScanStatus.PASSED: "\u2705",
                ScanStatus.FAILED: "\u274c",
                ScanStatus.PENDING: "\u23f3",
                ScanStatus.NOT_REQUIRED: "\u2796",
            }
            test_icon = icons.get(arch.test_status, "\u2753")
            scan_icon = scan_icons.get(arch.scan_status, "\u2753")
            err = f" \u2014 {arch.error_message}" if arch.error_message else ""
            lines.append(
                f"| `{arch.architecture}` | `{arch.digest[:20]}...` | "
                f"Tests: {test_icon} | Scan: {scan_icon}{err} |"
            )

        lines.append("")
        ready = manifest.is_release_ready()
        manifest_status = "ALLOWED" if ready else "BLOCKED"
        lines.append(f"**Manifest push {manifest_status}**")
        if not ready:
            missing = self._find_missing_validation(manifest)
            failed = self._find_failed(manifest)
            reasons = []
            if missing:
                names = ", ".join(a.architecture for a in missing)
                reasons.append(f"Missing validation: {names}")
            if failed:
                names = ", ".join(a.architecture for a in failed)
                reasons.append(f"Failed validation: {names}")
            lines.append(f"Reason: {'; '.join(reasons)}")
        lines.append("")
        return "\n".join(lines)

    # -- Internal helpers --

    def _validate_not_empty(self, manifest: MultiArchManifest) -> None:
        if not manifest.architectures:
            raise ManifestValidationError(
                f"No architectures registered for {manifest.image_name}:{manifest.tag}. "
                "At least one architecture must be registered before release."
            )

    def _find_missing_validation(self, manifest: MultiArchManifest) -> List[ArchitectureDigest]:
        return [
            a for a in manifest.architectures
            if a.test_status in (ValidationStatus.PENDING, ValidationStatus.SKIPPED)
               or a.scan_status in (ScanStatus.PENDING,)
        ]

    def _find_failed(self, manifest: MultiArchManifest) -> List[ArchitectureDigest]:
        return [
            a for a in manifest.architectures
            if a.test_status == ValidationStatus.FAILED
               or a.scan_status == ScanStatus.FAILED
        ]

    def _format_missing(self, manifest: MultiArchManifest,
                        missing: List[ArchitectureDigest]) -> str:
        arch_details = []
        for arch in missing:
            parts = [f"{arch.architecture} ({arch.digest[:16]}...)"]
            if arch.test_status == ValidationStatus.PENDING:
                parts.append("tests pending")
            if arch.scan_status == ScanStatus.PENDING:
                parts.append("scan pending")
            arch_details.append(", ".join(parts))
        return (
            f"Manifest push blocked \u2014 incomplete validation coverage: "
            f"{'; '.join(arch_details)}. "
            f"All architecture digests must pass test and scan gates "
            f"before manifest publication."
        )

    def _format_failed(self, failed: List[ArchitectureDigest]) -> str:
        arch_details = []
        for arch in failed:
            err = f" ({arch.error_message})" if arch.error_message else ""
            arch_details.append(f"{arch.architecture}{err}")
        return (
            f"Manifest push blocked \u2014 validation failures: "
            f"{'; '.join(arch_details)}"
        )

    def _validate_full_coverage(self, manifest: MultiArchManifest) -> None:
        pass
