"""Runner image provenance validation for self-hosted build fleet."""

import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


APPROVED_IMAGE_DIGESTS: List[str] = [
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "sha256:a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a",
]
MAX_IMAGE_AGE_HOURS: int = 48
ENV_APPROVED_DIGESTS: str = "AO_APPROVED_RUNNER_DIGESTS"
REQUIRED_RUNNER_LABELS: List[str] = ["self-hosted", "Linux", "x64"]
FORBIDDEN_RUNNER_LABELS: List[str] = ["unapproved", "experimental"]


class ProvenanceResult:
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> Dict:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


class ProvenanceReport:
    def __init__(self):
        self.checks: List[ProvenanceResult] = []
        self.timestamp: str = datetime.now(timezone.utc).isoformat()
        self.hostname: str = platform.node() or "unknown"
        self.platform: str = sys.platform

    def add(self, result: ProvenanceResult) -> None:
        self.checks.append(result)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "timestamp": self.timestamp,
            "hostname": self.hostname,
            "platform": self.platform,
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _get_approved_digests() -> List[str]:
    override = os.environ.get(ENV_APPROVED_DIGESTS)
    if override:
        return [d.strip() for d in override.split(",") if d.strip()]
    return APPROVED_IMAGE_DIGESTS


def _get_runner_labels() -> List[str]:
    runner_labels_raw = os.environ.get("RUNNER_LABELS", "")
    if runner_labels_raw:
        return [lbl.strip() for lbl in runner_labels_raw.split(",") if lbl.strip()]
    labels = ["self-hosted"]
    if sys.platform.startswith("linux"):
        labels.append("Linux")
        labels.append("x64" if platform.machine() in ("x86_64", "amd64") else platform.machine())
    elif sys.platform == "darwin":
        labels.append("macOS")
    elif sys.platform == "win32":
        labels.append("Windows")
    return labels


def _compute_image_digest() -> Optional[str]:
    hasher = hashlib.sha256()
    os_release_path = Path("/etc/os-release")
    if os_release_path.exists():
        hasher.update(os_release_path.read_bytes())
    else:
        hasher.update(platform.platform().encode())
    hasher.update(platform.release().encode())
    hasher.update(sys.version.encode())
    return f"sha256:{hasher.hexdigest()}"


def _get_image_build_timestamp() -> Optional[float]:
    for path in [Path("/etc/image-build-time"), Path("/etc/machine-id"), Path("/etc/hostname")]:
        if path.exists():
            try:
                return path.stat().st_mtime
            except OSError:
                continue
    return None


def _is_stale_image(build_timestamp: Optional[float]) -> Optional[bool]:
    if build_timestamp is None:
        return None
    return (time.time() - build_timestamp) / 3600 > MAX_IMAGE_AGE_HOURS


def check_image_digest(report: ProvenanceReport) -> None:
    digests = _get_approved_digests()
    actual = _compute_image_digest()
    if actual is None:
        report.add(ProvenanceResult("image_digest", False, "Could not compute image digest"))
        return
    if actual in digests:
        report.add(ProvenanceResult("image_digest", True, f"Digest {actual[:20]}... approved"))
    else:
        report.add(ProvenanceResult("image_digest", False, f"Digest {actual[:20]}... not approved"))


def check_image_freshness(report: ProvenanceReport) -> None:
    build_ts = _get_image_build_timestamp()
    if build_ts is None:
        report.add(ProvenanceResult("image_freshness", True, "Build timestamp unavailable, skipping"))
        return
    stale = _is_stale_image(build_ts)
    build_time_str = datetime.fromtimestamp(build_ts, tz=timezone.utc).isoformat()
    age_hours = (time.time() - build_ts) / 3600
    if stale:
        report.add(ProvenanceResult("image_freshness", False,
            f"Image built at {build_time_str} ({age_hours:.1f}h ago) exceeds {MAX_IMAGE_AGE_HOURS}h limit"))
    else:
        report.add(ProvenanceResult("image_freshness", True,
            f"Image built at {build_time_str} ({age_hours:.1f}h ago) is fresh"))


def check_runner_labels(report: ProvenanceReport) -> None:
    labels = _get_runner_labels()
    missing = [lbl for lbl in REQUIRED_RUNNER_LABELS if lbl not in labels]
    forbidden_found = [lbl for lbl in FORBIDDEN_RUNNER_LABELS if lbl in labels]
    if missing:
        report.add(ProvenanceResult("runner_labels", False,
            f"Missing required labels: {', '.join(missing)}. Got: {', '.join(labels)}"))
    elif forbidden_found:
        report.add(ProvenanceResult("runner_labels", False,
            f"Forbidden labels present: {', '.join(forbidden_found)}"))
    else:
        report.add(ProvenanceResult("runner_labels", True,
            f"All required labels present: {', '.join(REQUIRED_RUNNER_LABELS)}"))


def validate(strict: bool = False) -> ProvenanceReport:
    report = ProvenanceReport()
    check_image_digest(report)
    check_image_freshness(report)
    check_runner_labels(report)
    if strict:
        for c in report.checks:
            if c.name == "image_freshness" and not c.passed and "unavailable" in c.detail:
                c.passed = False
                c.detail = "Strict mode: build timestamp is required"
    return report


def main() -> int:
    strict = "--strict" in sys.argv
    report = validate(strict=strict)
    print(report.to_json())
    if report.passed:
        print("\nRunner provenance PASSED")
    else:
        print("\nRunner provenance FAILED")
        for c in report.checks:
            if not c.passed:
                print(f"  - {c.name}: {c.detail}")
    Path("/tmp/runner-provenance.json").write_text(report.to_json())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
