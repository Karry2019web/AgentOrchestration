"""Webhook signature verification and replay window enforcement."""

import hmac
import hashlib
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Default replay window: 5 minutes
DEFAULT_REPLAY_WINDOW_SECONDS = 300

# Maximum allowed clock skew between signer and verifier
MAX_CLOCK_SKEW_SECONDS = 60


class WebhookSignatureError(Exception):
    """Raised when webhook signature validation fails."""
    pass


class ReplayAttackError(WebhookSignatureError):
    """Raised when a replayed webhook payload is detected."""
    pass


class WebhookVerifier:
    """Verifies HMAC-SHA256 webhook signatures with timestamp-based replay protection.

    Implements the ``Enforce replay window on webhook signatures`` requirement
    from the inbound security specification.  Every signed payload includes a
    ``t`` (timestamp) claim and an ``s`` (signature) claim.  Signatures older
    than ``replay_window`` seconds are unconditionally rejected, preventing
    replay attacks from captured or leaked payloads.
    """

    def __init__(self, secret: str, replay_window: int = DEFAULT_REPLAY_WINDOW_SECONDS):
        self._secret = secret.encode("utf-8") if isinstance(secret, str) else secret
        self._replay_window = replay_window

    @property
    def replay_window(self) -> int:
        return self._replay_window

    def sign(self, payload: dict) -> Tuple[str, str]:
        """Return (signature, timestamp) for *payload*.

        The timestamp is an ISO-8601 UTC string.  The signature is an
        HMAC-SHA256 hex digest over ``timestamp.payload_json``.
        """
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = f"{ts}.{json.dumps(payload, separators=(',', ':'))}".encode("utf-8")
        sig = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
        return sig, ts

    def sign_header(self, payload: dict) -> str:
        """Return a ``t=...;s=...`` signature header value."""
        sig, ts = self.sign(payload)
        return f"t={ts};s={sig}"

    def verify(self, payload: dict, header: str) -> dict:
        """Validate *header* (``t=...;s=...``) against *payload*.

        Returns the parsed timestamp dict on success:

            {"timestamp": "2026-05-23T12:00:00Z", "age_seconds": 12.3}

        Raises:
            WebhookSignatureError - malformed header, missing fields
            ReplayAttackError     - signature outside the replay window
            WebhookSignatureError - HMAC mismatch (tampered payload/header)
        """
        ts_str, sig = self._parse_header(header)
        parsed_ts = self._parse_timestamp(ts_str)
        age = (datetime.utcnow() - parsed_ts).total_seconds()

        if age < 0 and abs(age) > MAX_CLOCK_SKEW_SECONDS:
            raise ReplayAttackError(
                f"Timestamp {ts_str} is {abs(age):.0f}s in the future "
                f"(clock skew > {MAX_CLOCK_SKEW_SECONDS}s)"
            )

        if age > self._replay_window:
            raise ReplayAttackError(
                f"Signature expired: {age:.0f}s old "
                f"(replay window = {self._replay_window}s)"
            )

        raw = f"{ts_str}.{json.dumps(payload, separators=(',', ':'))}".encode("utf-8")
        expected = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, sig):
            raise WebhookSignatureError("HMAC signature mismatch - payload or header tampered")

        logger.info("Webhook signature verified (age=%.1fs)", age)
        return {"timestamp": ts_str, "age_seconds": round(age, 1)}

    @staticmethod
    def _parse_header(header: str) -> Tuple[str, str]:
        """Extract t (timestamp) and s (signature) from header."""
        if not header:
            raise WebhookSignatureError("Empty signature header")
        parts = {}
        for item in header.split(";"):
            item = item.strip()
            if "=" not in item:
                continue
            key, _, val = item.partition("=")
            parts[key.strip()] = val.strip()
        ts = parts.get("t")
        sig = parts.get("s")
        if not ts:
            raise WebhookSignatureError("Missing t (timestamp) in signature header")
        if not sig:
            raise WebhookSignatureError("Missing s (signature) in signature header")
        return ts, sig

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime:
        """Parse ISO-8601 UTC timestamp."""
        try:
            ts_str = ts_str.replace("Z", "+00:00")
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError) as exc:
            raise WebhookSignatureError(f"Invalid timestamp format: {ts_str}") from exc


default_verifier: Optional[WebhookVerifier] = None


def configure(secret: str, replay_window: int = DEFAULT_REPLAY_WINDOW_SECONDS) -> WebhookVerifier:
    """Set the global default_verifier and return it."""
    global default_verifier
    default_verifier = WebhookVerifier(secret, replay_window)
    return default_verifier


def verify_webhook(payload: dict, header: str) -> dict:
    """Verify using the default_verifier (must call configure first)."""
    if default_verifier is None:
        raise RuntimeError("WebhookVerifier not configured - call configure(secret) first")
    return default_verifier.verify(payload, header)
