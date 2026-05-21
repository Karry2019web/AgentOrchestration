"""Deploy manifest dry-run validator for release preview.

Provides pre-deployment validation of rendered manifests including
schema validation, sensitive value redaction, and diff output.
"""

import json
import re
from typing import Any, Dict, List, Optional, Set


SENSITIVE_KEYS: Set[str] = {
    "password", "secret", "token", "api_key", "api-key",
    "apikey", "credential", "private_key", "access_key",
}


class ManifestValidationError(Exception):
    """Raised when a manifest fails dry-run validation."""


class ManifestRenderer:
    """Renders deployment manifests from templates and environment values."""

    def render(self, template: str, values: Dict[str, Any]) -> str:
        """Render a manifest template with the given values."""
        result = template
        for key, val in values.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(val))
            placeholder2 = "${{" + key + "}}"
            result = result.replace(placeholder2, str(val))
        return result


class ManifestValidator:
    """Validates rendered manifests against schema rules."""

    REQUIRED_FIELDS = ["apiVersion", "kind", "metadata"]

    def validate(self, manifest: str) -> List[str]:
        """Validate a rendered manifest string.

        Returns a list of error messages (empty = valid).
        """
        errors = []
        manifest = manifest.strip()
        if not manifest:
            return ["Manifest is empty"]

        # Try YAML-like or JSON parsing
        lines = manifest.split("\n")
        found_kind = False
        found_name = False
        found_apiversion = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("---"):
                continue
            if stripped.lower().startswith("apiversion:"):
                found_apiversion = True
                val = stripped.split(":", 1)[1].strip()
                if not val:
                    errors.append("apiVersion value is empty")
            if stripped.lower().startswith("kind:"):
                found_kind = True
                val = stripped.split(":", 1)[1].strip()
                if not val:
                    errors.append("kind value is empty")
            if stripped.lower().startswith("name:") or stripped.lower().startswith('  name:'):
                found_name = True

        if not found_apiversion:
            errors.append("Missing required field: apiVersion")
        if not found_kind:
            errors.append("Missing required field: kind")
        if not found_name:
            errors.append("Missing required field: metadata.name")

        # Check for unresolved template placeholders
        unresolved = re.findall(r"\{\{[^}]+\}\}|\$\{[^}]+\}", manifest)
        if unresolved:
            errors.append(f"Unresolved template placeholders: {unresolved}")

        return errors


class SensitiveValueRedactor:
    """Redacts sensitive values from manifest output for review."""

    def redact(self, manifest: str) -> str:
        """Replace sensitive values with [REDACTED] markers."""
        result = manifest
        for key in SENSITIVE_KEYS:
            # Match key: value patterns
            pattern = re.compile(
                rf'(\b{re.escape(key)}\b\s*[:=]\s*["\']?)([^"\'\n]+)',
                re.IGNORECASE
            )
            result = pattern.sub(r"\1[REDACTED]", result)
        return result


class DryRunManifest:
    """Combines rendering, validation, and redaction for dry-run preview."""

    def __init__(self):
        self.renderer = ManifestRenderer()
        self.validator = ManifestValidator()
        self.redactor = SensitiveValueRedactor()

    def preview(self, template: str, values: Dict[str, Any]) -> Dict:
        """Generate a dry-run preview of a rendered manifest.

        Returns:
            Dict with keys:
                - rendered: The raw rendered manifest string
                - redacted: Manifest with sensitive values redacted
                - valid: Whether the manifest passed validation
                - errors: List of validation errors (empty if valid)
        """
        rendered = self.renderer.render(template, values)
        redacted = self.redactor.redact(rendered)
        errors = self.validator.validate(rendered)

        return {
            "rendered": rendered,
            "redacted": redacted,
            "valid": len(errors) == 0,
            "errors": errors,
        }
