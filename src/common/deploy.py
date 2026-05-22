"""Deployment manifest rendering — immutable release identifiers."""

import hashlib
import time
from typing import Any, Dict, List, Optional
from threading import Lock


class ReleaseManifest:
    """An immutable deployment manifest with certified source and artifact identifiers."""

    def __init__(self, release_id: str, commit_sha: str, package_version: str,
                 image_digest: str, branch: str, deployed_at: float = None):
        self.release_id = release_id
        self.commit_sha = commit_sha
        self.package_version = package_version
        self.image_digest = image_digest
        self.branch = branch
        self.deployed_at = deployed_at or time.time()
        self._annotations: Dict[str, str] = {}

    def annotate(self, key: str, value: str) -> None:
        self._annotations[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "release_id": self.release_id,
            "commit_sha": self.commit_sha,
            "package_version": self.package_version,
            "image_digest": self.image_digest,
            "branch": self.branch,
            "deployed_at": self.deployed_at,
            "annotations": dict(self._annotations),
            "manifest_digest": self._compute_digest(),
        }

    def _compute_digest(self) -> str:
        raw = f"{self.release_id}:{self.commit_sha}:{self.package_version}:{self.image_digest}"
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


class DeployManifestRenderer:
    """Renders deployment manifests with immutable identifiers instead of mutable branch names."""

    def __init__(self):
        self._lock = Lock()
        self._releases: Dict[str, ReleaseManifest] = {}
        self._history: List[ReleaseManifest] = []

    def render_manifest(self, release_id: str, commit_sha: str,
                        package_version: str, image_digest: str,
                        branch: str = "") -> ReleaseManifest:
        """Render a release manifest using immutable identifiers."""
        if not commit_sha:
            raise ValueError("commit_sha is required for immutable release identifiers")
        if not image_digest:
            raise ValueError("image_digest is required for immutable release identifiers")
        if not package_version:
            raise ValueError("package_version is required for immutable release identifiers")

        manifest = ReleaseManifest(
            release_id=release_id,
            commit_sha=commit_sha,
            package_version=package_version,
            image_digest=image_digest,
            branch=branch or "unknown",
        )
        manifest.annotate("rendered_by", "DeployManifestRenderer")
        manifest.annotate("immutable", "true")

        with self._lock:
            self._releases[release_id] = manifest
            self._history.append(manifest)

        return manifest

    def get_release(self, release_id: str) -> Optional[Dict]:
        with self._lock:
            m = self._releases.get(release_id)
            return m.to_dict() if m else None

    def query_by_commit(self, commit_sha: str) -> List[Dict]:
        with self._lock:
            return [
                m.to_dict()
                for m in self._history
                if m.commit_sha == commit_sha
            ]

    def query_by_identifier(self, identifier_type: str, value: str) -> List[Dict]:
        """Query deployment history by immutable identifier type."""
        with self._lock:
            results = []
            for m in self._history:
                d = m.to_dict()
                if d.get(identifier_type) == value:
                    results.append(d)
            return results

    def get_deployment_history(self, limit: int = 20) -> List[Dict]:
        with self._lock:
            return [m.to_dict() for m in self._history[-limit:]]


deploy_renderer = DeployManifestRenderer()
