"""Tests for deploy manifest dry-run validation."""

import pytest
from src.deploy.manifest import (
    ManifestRenderer,
    ManifestValidator,
    SensitiveValueRedactor,
    DryRunManifest,
)


class TestManifestRenderer:
    def test_render_simple_placeholder(self):
        renderer = ManifestRenderer()
        result = renderer.render("apiVersion: {{version}}", {"version": "v1"})
        assert result == "apiVersion: v1"

    def test_render_multiple_placeholders(self):
        renderer = ManifestRenderer()
        result = renderer.render(
            "name: {{name}}\nkind: {{kind}}",
            {"name": "test-app", "kind": "Deployment"}
        )
        assert "name: test-app" in result
        assert "kind: Deployment" in result

    def test_render_github_style_placeholder(self):
        renderer = ManifestRenderer()
        result = renderer.render("version: ${{version}}", {"version": "1.0"})
        assert result == "version: 1.0"

    def test_render_empty_values(self):
        renderer = ManifestRenderer()
        result = renderer.render("key: {{key}}", {})
        assert "{{key}}" in result  # Unresolved


class TestManifestValidator:
    def test_valid_manifest_passes(self):
        validator = ManifestValidator()
        errors = validator.validate(
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: test-app"
        )
        assert len(errors) == 0

    def test_empty_manifest_fails(self):
        validator = ManifestValidator()
        errors = validator.validate("")
        assert len(errors) > 0

    def test_missing_apiversion_fails(self):
        validator = ManifestValidator()
        errors = validator.validate("kind: Pod\nmetadata:\n  name: test")
        assert any("apiVersion" in e for e in errors)

    def test_missing_kind_fails(self):
        validator = ManifestValidator()
        errors = validator.validate("apiVersion: v1\nmetadata:\n  name: test")
        assert any("kind" in e for e in errors)

    def test_unresolved_placeholder_fails(self):
        validator = ManifestValidator()
        errors = validator.validate(
            "apiVersion: v1\nkind: Pod\nmetadata:\n  name: {{unresolved}}"
        )
        assert any("placeholder" in e.lower() for e in errors)


class TestSensitiveValueRedactor:
    def test_redact_password(self):
        redactor = SensitiveValueRedactor()
        result = redactor.redact("password: mysecret123")
        assert "[REDACTED]" in result
        assert "mysecret123" not in result

    def test_redact_token(self):
        redactor = SensitiveValueRedactor()
        result = redactor.redact("token: ghp_abc123")
        assert "[REDACTED]" in result

    def test_redact_apikey(self):
        redactor = SensitiveValueRedactor()
        result = redactor.redact("api_key: "sk-123456"")
        assert "[REDACTED]" in result

    def test_regular_value_not_redacted(self):
        redactor = SensitiveValueRedactor()
        result = redactor.redact("replicas: 3")
        assert "[REDACTED]" not in result


class TestDryRunManifest:
    def test_full_preview_success(self):
        dryrun = DryRunManifest()
        result = dryrun.preview(
            "apiVersion: {{ver}}\nkind: {{type}}\nmetadata:\n  name: {{name}}",
            {"ver": "v1", "type": "Deployment", "name": "test"}
        )
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert "apiVersion: v1" in result["rendered"]

    def test_full_preview_with_errors(self):
        dryrun = DryRunManifest()
        result = dryrun.preview(
            "kind: {{type}}",
            {"type": "Pod"}
        )
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_sensitive_value_redacted_in_preview(self):
        dryrun = DryRunManifest()
        result = dryrun.preview(
            "name: app\npassword: {{secret}}",
            {"secret": "super-secret-value"}
        )
        assert "[REDACTED]" in result["redacted"]
        assert "super-secret-value" not in result["redacted"]
