"""Tests for immutable release manifest rendering."""

import pytest
from src.common.deploy import DeployManifestRenderer


class TestDeployManifestRenderer:
    def setup_method(self):
        self.renderer = DeployManifestRenderer()

    def test_render_manifest(self):
        manifest = self.renderer.render_manifest(
            "rel-1", "abc123def456", "1.2.3",
            "sha256:deadbeef", "main"
        )
        d = manifest.to_dict()
        assert d["release_id"] == "rel-1"
        assert d["commit_sha"] == "abc123def456"
        assert d["package_version"] == "1.2.3"
        assert d["image_digest"] == "sha256:deadbeef"
        assert d["manifest_digest"].startswith("sha256:")

    def test_manifest_digest_is_immutable_check(self):
        m1 = self.renderer.render_manifest("r1", "sha1", "1.0", "img1", "main")
        m2 = self.renderer.render_manifest("r2", "sha2", "1.1", "img2", "main")
        assert m1.to_dict()["manifest_digest"] != m2.to_dict()["manifest_digest"]

    def test_missing_commit_sha_raises(self):
        with pytest.raises(ValueError, match="commit_sha is required"):
            self.renderer.render_manifest("r3", "", "1.0", "img1")

    def test_missing_image_digest_raises(self):
        with pytest.raises(ValueError, match="image_digest is required"):
            self.renderer.render_manifest("r4", "sha1", "1.0", "")

    def test_get_release(self):
        self.renderer.render_manifest("r5", "sha1", "1.0", "img1", "main")
        rel = self.renderer.get_release("r5")
        assert rel is not None
        assert rel["release_id"] == "r5"

    def test_get_release_nonexistent(self):
        assert self.renderer.get_release("nonexistent") is None

    def test_query_by_commit(self):
        self.renderer.render_manifest("r6", "commit-a", "1.0", "img-a", "main")
        self.renderer.render_manifest("r7", "commit-a", "1.1", "img-b", "hotfix")
        results = self.renderer.query_by_commit("commit-a")
        assert len(results) == 2

    def test_branch_not_primary_identity(self):
        """Branch names should not be the primary release identity."""
        m = self.renderer.render_manifest("r8", "sha-final", "2.0", "img-final", "feature-x")
        d = m.to_dict()
        # The primary identity should be from immutable identifiers
        assert d["release_id"] == "r8"
        assert d["manifest_digest"] is not None

    def test_deployment_history(self):
        for i in range(5):
            self.renderer.render_manifest(f"r{i}", f"sha{i}", f"1.{i}", f"img{i}", "main")
        history = self.renderer.get_deployment_history(limit=3)
        assert len(history) == 3
        assert history[-1]["release_id"] == "r4"
