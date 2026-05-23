import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
import yaml


SAMPLE_EXCEPTIONS = {
    "exceptions": [
        {
            "dependency": "vulnerable-pkg==1.0.0",
            "reason": "Upstream fix tracked in #1234",
            "owner": "security-team",
            "expires": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d"),
            "created": "2026-05-01",
        },
        {
            "dependency": "actions/setup-python@v4",
            "reason": "Migration to v5 planned Q3",
            "owner": "devops@example.com",
            "expires": (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d"),
            "created": "2026-05-15",
        },
    ]
}


def _write_manifest(content: dict, tmpdir: str) -> str:
    path = os.path.join(tmpdir, "dependency-exceptions.yml")
    with open(path, "w") as f:
        yaml.dump(content, f)
    return path


@pytest.fixture
def exceptions_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _run_validation(exceptions_dir):
    """Simulate the inline Python validation from the CI workflow."""
    manifest_path = os.path.join(exceptions_dir, "dependency-exceptions.yml")
    if not os.path.exists(manifest_path):
        return True

    with open(manifest_path) as f:
        data = yaml.safe_load(f)
    exceptions = data.get("exceptions", [])
    if not exceptions:
        return True

    now = datetime.now(timezone.utc).date()
    for exc in exceptions:
        assert exc.get("owner"), f"Missing owner: {exc}"
        assert exc.get("reason"), f"Missing reason: {exc}"
        exp = datetime.fromisoformat(exc["expires"]).date()
        assert exp >= now, f"Expired: {exc}"
        assert exc.get("created"), f"Missing created: {exc}"
    return True


def test_all_exceptions_valid(exceptions_dir):
    """Valid exceptions pass validation."""
    path = _write_manifest(SAMPLE_EXCEPTIONS, exceptions_dir)
    assert _run_validation(exceptions_dir) is True


def test_missing_owner_fails(exceptions_dir):
    """Exception without owner fails validation."""
    bad = {
        "exceptions": [
            {
                "dependency": "bad-pkg",
                "reason": "Some reason",
                "expires": "2027-01-01",
                "created": "2026-05-01",
            }
        ]
    }
    _write_manifest(bad, exceptions_dir)
    with pytest.raises(AssertionError, match="Missing owner"):
        _run_validation(exceptions_dir)


def test_missing_reason_fails(exceptions_dir):
    """Exception without reason fails validation."""
    bad = {
        "exceptions": [
            {
                "dependency": "bad-pkg",
                "owner": "alice",
                "expires": "2027-01-01",
                "created": "2026-05-01",
            }
        ]
    }
    _write_manifest(bad, exceptions_dir)
    with pytest.raises(AssertionError, match="Missing reason"):
        _run_validation(exceptions_dir)


def test_expired_exception_fails(exceptions_dir):
    """Expired exception fails validation."""
    bad = {
        "exceptions": [
            {
                "dependency": "old-pkg",
                "reason": "Was waiting on upgrade",
                "owner": "bob",
                "expires": "2020-01-01",
                "created": "2019-12-01",
            }
        ]
    }
    _write_manifest(bad, exceptions_dir)
    with pytest.raises(AssertionError, match="Expired"):
        _run_validation(exceptions_dir)


def test_empty_manifest_passes(exceptions_dir):
    """Empty manifest passes validation."""
    _write_manifest({}, exceptions_dir)
    assert _run_validation(exceptions_dir) is True


def test_no_exceptions_passes(exceptions_dir):
    """Manifest with empty exceptions list passes."""
    _write_manifest({"exceptions": []}, exceptions_dir)
    assert _run_validation(exceptions_dir) is True
