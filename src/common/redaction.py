"""Shared redaction policy for structured data exports.

All export formats (JSON, CSV, UI) use this single policy definition
to ensure consistent data masking. Adding a new export field requires
explicit policy classification.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class FieldClassification(Enum):
    """Classification of export fields for redaction policy."""
    PUBLIC = "public"           # Safe to export in any format
    INTERNAL = "internal"       # Exportable with warning
    RESTRICTED = "restricted"   # Masked in exports
    SENSITIVE = "sensitive"     # Omitted entirely from exports


@dataclass
class RedactionPolicy:
    """Defines how a field is treated during export serialization."""

    field_name: str
    classification: FieldClassification = FieldClassification.PUBLIC
    mask_char: str = "*"
    mask_length: int = 4
    redact_if: Optional[Callable[[Any], bool]] = None

    def redact_value(self, value: Any) -> Any:
        """Apply redaction to a value based on this policy."""
        if self.classification == FieldClassification.PUBLIC:
            return value

        if self.classification == FieldClassification.INTERNAL:
            return value

        if self.classification == FieldClassification.RESTRICTED:
            if self.redact_if and not self.redact_if(value):
                return value
            s = str(value)
            if len(s) <= self.mask_length:
                return self.mask_char * len(s)
            return s[:self.mask_length] + self.mask_char * min(
                self.mask_length, max(1, len(s) - self.mask_length)
            )

        if self.classification == FieldClassification.SENSITIVE:
            return "[REDACTED]"

        return value


DEFAULT_POLICIES: Dict[str, RedactionPolicy] = {
    "api_key": RedactionPolicy("api_key", FieldClassification.SENSITIVE),
    "password": RedactionPolicy("password", FieldClassification.SENSITIVE),
    "secret": RedactionPolicy("secret", FieldClassification.SENSITIVE),
    "token": RedactionPolicy("token", FieldClassification.RESTRICTED,
                             mask_length=8, redact_if=lambda v: bool(v)),
    "session_id": RedactionPolicy("session_id", FieldClassification.RESTRICTED),
    "internal_ip": RedactionPolicy("internal_ip", FieldClassification.INTERNAL),
    "hostname": RedactionPolicy("hostname", FieldClassification.INTERNAL),
    "agent_name": RedactionPolicy("agent_name", FieldClassification.PUBLIC),
    "workflow_id": RedactionPolicy("workflow_id", FieldClassification.PUBLIC),
    "task_id": RedactionPolicy("task_id", FieldClassification.PUBLIC),
    "status": RedactionPolicy("status", FieldClassification.PUBLIC),
    "timestamp": RedactionPolicy("timestamp", FieldClassification.PUBLIC),
    "tenant_id": RedactionPolicy("tenant_id", FieldClassification.INTERNAL),
    "error_message": RedactionPolicy("error_message", FieldClassification.RESTRICTED),
    "stack_trace": RedactionPolicy("stack_trace", FieldClassification.SENSITIVE),
}


class RedactionSerializer:
    """Serializes structured data with consistent redaction policy.

    All export formats (JSON, CSV, UI views) should use this serializer
    instead of directly serializing internal data.
    """

    def __init__(self, policies: Optional[Dict[str, RedactionPolicy]] = None):
        self._policies = dict(DEFAULT_POLICIES)
        if policies:
            self._policies.update(policies)

    def register_policy(self, policy: RedactionPolicy) -> None:
        """Register or update a field policy."""
        self._policies[policy.field_name] = policy

    def get_policy(self, field_name: str) -> Optional[RedactionPolicy]:
        """Get the policy for a field, or None if no policy exists."""
        return self._policies.get(field_name)

    def classify(self, field_name: str) -> FieldClassification:
        """Get the classification for a field."""
        policy = self._policies.get(field_name)
        if policy:
            return policy.classification
        return FieldClassification.PUBLIC

    def redact_field(self, field_name: str, value: Any) -> Any:
        """Redact a single field value according to policy."""
        policy = self._policies.get(field_name)
        if policy:
            return policy.redact_value(value)
        return value

    def serialize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a record with redaction applied to all fields.

        Returns a copy with redacted values — original data is not mutated.
        """
        result: Dict[str, Any] = {}
        for key, value in data.items():
            result[key] = self.redact_field(key, value)
        return result

    def serialize_many(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Serialize multiple records with consistent redaction."""
        return [self.serialize(r) for r in records]
