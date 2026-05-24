"""Synthetic test fixtures for data processing modules.

All fixtures in this module use purely synthetic data.
No real-world samples, secrets, or sensitive data are included.

This module is the authoritative source for test data across
parser, exporter, and validation tests.
"""

import json


SAMPLE_LOG_LINES = [
    "[INFO] 2026-01-01T00:00:00Z Worker started",
    "[INFO] 2026-01-01T00:01:00Z Task completed: id=abc-123",
    "[WARN] 2026-01-01T00:02:00Z Retrying task id=def-456",
    "[ERROR] 2026-01-01T00:03:00Z Timeout on task id=ghi-789",
]

SAMPLE_EVENTS = [
    {"event": "deploy", "env": "staging", "version": "v2.5.0"},
    {"event": "rollback", "env": "production", "version": "v2.4.9"},
    {"event": "scale", "env": "staging", "replicas": 5},
]


SAMPLE_EXPORT_RECORDS = [
    {"id": f"rec-{i:04d}", "name": f"item-{i}", "value": i * 10}
    for i in range(1, 11)
]

SAMPLE_EXPORT_CSV = (
    "id,name,value\n"
    "rec-0001,item-1,10\n"
    "rec-0002,item-2,20\n"
)


VALID_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "count": {"type": "integer", "minimum": 0},
    },
    "required": ["id"],
}

VALID_PAYLOAD = {"id": "test-001", "count": 42}
INVALID_PAYLOAD = {"id": "test-002", "count": -1}


def make_synthetic_batch(size: int = 5) -> list[dict]:
    """Generate a batch of synthetic records for testing."""
    return [
        {"seq": i, "label": f"syn-{i}", "ts": 1000 + i}
        for i in range(size)
    ]


def sanitized_fixture_paths() -> list[str]:
    """Return paths under tests/ that are approved for fixture data."""
    return [
        "tests/data/synthetic_fixtures.py",
    ]
