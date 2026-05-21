"""Tests for network-disabled Docker final packaging."""
import sys
from unittest.mock import MagicMock
sys.modules["resource"] = MagicMock()
import src.agent
src.agent.AgentStatus = MagicMock()
src.agent.AgentRegistry = MagicMock()

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
POLICY_DOC = ROOT / "docs" / "docker-build-network-policy.md"
DOCKERIGNORE = ROOT / ".dockerignore"
MAKEFILE = ROOT / "Makefile"
README = ROOT / "README.md"


def _parse_stage(name: str):
    """Return all lines inside Dockerfile stage *name*."""
    content = DOCKERFILE.read_text(encoding="utf-8")
    lines = content.splitlines()
    stage_start = None
    stage_end = None
    for i, line in enumerate(lines):
        stripped = line.strip().upper()
        if stripped.startswith("FROM ") and f" AS {name.upper()}" in stripped:
            stage_start = i + 1
        elif stage_start is not None and stripped.startswith("FROM "):
            stage_end = i
            break
    if stage_start is None:
        return []
    stage = lines[stage_start:stage_end]
    return [l.strip() for l in stage if l.strip() and not l.strip().startswith("#")]


def _assert_file_exists(path, description):
    assert path.exists(), f"Missing {description}: {path}"


class TestDockerfileStructure:

    def test_dockerfile_exists(self):
        _assert_file_exists(DOCKERFILE, "Dockerfile")

    def test_dockerignore_exists(self):
        _assert_file_exists(DOCKERIGNORE, ".dockerignore")

    def test_policy_doc_exists(self):
        _assert_file_exists(POLICY_DOC, "docker-build-network-policy.md")

    def test_final_stage_has_network_none_on_all_run(self):
        stage = _parse_stage("final")
        run_lines = [l for l in stage if l.upper().startswith("RUN ")]
        assert run_lines, "final stage must have at least one RUN instruction"
        assert all("--network=none" in l for l in run_lines), (
            "Every RUN in final stage must use --network=none"
        )

    def test_final_stage_no_package_managers(self):
        stage_text = "\n".join(_parse_stage("final")).lower()
        forbidden = [" pip ", " pip install", " uv pip", " apt", " apt-get",
                      " apk add", " yum install", " brew install",
                      " cargo install", " npm install", " go install"]
        for cmd in forbidden:
            assert cmd not in stage_text, f"forbidden command '{cmd}' found in final stage"

    def test_final_stage_copies_from_dependency(self):
        stage_text = "\n".join(_parse_stage("final")).lower()
        assert "copy --from=dependency-resolver" in stage_text, (
            "final stage must COPY from dependency-resolver"
        )

    def test_dependency_stage_allows_uv_pip(self):
        stage_text = "\n".join(_parse_stage("dependency-resolver")).lower()
        assert "pip install" in stage_text or "uv pip" in stage_text

    def test_dockerignore_excludes_unnecessary(self):
        content = DOCKERIGNORE.read_text(encoding="utf-8")
        assert ".git" in content
        assert ".github" in content
        assert "Dockerfile" in content

    def test_ci_has_docker_final_job(self):
        content = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "docker-final-stage" in content
        assert "--target final" in content
        assert "--check" in content

    def test_makefile_uses_buildkit(self):
        content = MAKEFILE.read_text(encoding="utf-8")
        assert "DOCKER_BUILDKIT=1" in content
        assert "--target final" in content

    def test_readme_references_policy(self):
        content = README.read_text(encoding="utf-8")
        assert "docker-build-network-policy.md" in content

    def test_policy_doc_lists_stages_and_network_rules(self):
        content = POLICY_DOC.read_text(encoding="utf-8")
        assert "dependency-resolver" in content
        assert "final" in content
        assert "--network=none" in content
        assert "BuildKit" in content
