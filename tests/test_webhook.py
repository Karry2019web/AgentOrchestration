"""Tests for webhook signature verification with replay window enforcement."""

import time
import json
import pytest
from datetime import datetime, timedelta

from src.common.webhook import (
    WebhookVerifier,
    WebhookSignatureError,
    ReplayAttackError,
    configure,
    verify_webhook,
    DEFAULT_REPLAY_WINDOW_SECONDS,
)


class TestWebhookVerifier:
    """Coverage: valid delivery, rejected delivery, retry behavior."""

    def setup_method(self):
        self.secret = "test-secret-key"
        self.verifier = WebhookVerifier(self.secret)
        self.payload = {"event": "agent.started", "agent_id": "a-123", "ts": "2026-05-23T12:00:00Z"}

    def test_sign_and_verify_roundtrip(self):
        """Valid delivery: correctly signed payload passes verification."""
        header = self.verifier.sign_header(self.payload)
        result = self.verifier.verify(self.payload, header)
        assert "timestamp" in result
        assert "age_seconds" in result
        assert result["age_seconds"] < 5  # just created

    def test_replay_rejected(self):
        """Rejected delivery: expired signature is detected as replay."""
        # Create a verifier with a very short window
        fast_verifier = WebhookVerifier(self.secret, replay_window=1)
        header = fast_verifier.sign_header(self.payload)
        time.sleep(1.5)
        with pytest.raises(ReplayAttackError, match="replay window"):
            fast_verifier.verify(self.payload, header)

    def test_tampered_payload_rejected(self):
        """Rejected delivery: HMAC mismatch catches tampered payload."""
        header = self.verifier.sign_header(self.payload)
        tampered = dict(self.payload)
        tampered["agent_id"] = "a-999"
        with pytest.raises(WebhookSignatureError, match="HMAC"):
            self.verifier.verify(tampered, header)

    def test_tampered_signature_rejected(self):
        """Rejected delivery: modified header is detected."""
        header = self.verifier.sign_header(self.payload)
        bad_header = header.replace("s=", "s=bad")
        with pytest.raises(WebhookSignatureError):
            self.verifier.verify(self.payload, bad_header)

    def test_missing_header_rejected(self):
        """Rejected delivery: empty header raises error."""
        with pytest.raises(WebhookSignatureError, match="Empty"):
            self.verifier.verify(self.payload, "")

    def test_missing_timestamp_in_header(self):
        """Rejected delivery: header without t= field."""
        sig, _ = self.verifier.sign(self.payload)
        header = f"s={sig}"
        with pytest.raises(WebhookSignatureError, match="timestamp"):
            self.verifier.verify(self.payload, header)

    def test_missing_signature_in_header(self):
        """Rejected delivery: header without s= field."""
        _, ts = self.verifier.sign(self.payload)
        header = f"t={ts}"
        with pytest.raises(WebhookSignatureError, match="signature"):
            self.verifier.verify(self.payload, header)

    def test_future_timestamp_rejected(self):
        """Rejected delivery: timestamp more than 60s in future."""
        future_ts = (datetime.utcnow() + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = f"{future_ts}.{json.dumps(self.payload, separators=(',', ':'))}".encode("utf-8")
        import hmac, hashlib
        sig = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        header = f"t={future_ts};s={sig}"
        with pytest.raises(ReplayAttackError, match="clock skew"):
            self.verifier.verify(self.payload, header)

    def test_retry_idempotent(self):
        """Retry behavior: same signed payload rejected on second verify after window expires."""
        short_verifier = WebhookVerifier(self.secret, replay_window=2)
        header = short_verifier.sign_header(self.payload)
        # First call succeeds
        result = short_verifier.verify(self.payload, header)
        assert result["age_seconds"] < 2
        # After window expires, same signature is rejected
        time.sleep(2.5)
        with pytest.raises(ReplayAttackError):
            short_verifier.verify(self.payload, header)

    def test_workspace_isolation(self):
        """Workspace isolation: different secrets produce different signatures."""
        v1 = WebhookVerifier("secret-a")
        v2 = WebhookVerifier("secret-b")
        h1 = v1.sign_header(self.payload)
        h2 = v2.sign_header(self.payload)
        assert h1 != h2
        # v1's header fails with v2
        with pytest.raises(WebhookSignatureError):
            v2.verify(self.payload, h1)

    def test_json_payload_order_independence(self):
        """Payload serialization is order-independent for signature computation."""
        p1 = {"a": 1, "b": 2}
        p2 = {"b": 2, "a": 1}
        h1 = self.verifier.sign_header(p1)
        h2 = self.verifier.sign_header(p2)
        # Same logical payload -> same signature
        result = self.verifier.verify(p1, h2)
        assert result["age_seconds"] >= 0


class TestWebhookVerifierConfiguration:
    """Coverage for the global configure/verify_webhook helpers."""

    def teardown_method(self):
        from src.common.webhook import default_verifier
        import src.common.webhook as wh
        wh.default_verifier = None

    def test_configure_sets_global(self):
        verifier = configure("my-secret")
        assert verifier is not None
        from src.common.webhook import default_verifier
        assert default_verifier is not None

    def test_verify_webhook_with_global(self):
        configure("global-secret")
        payload = {"msg": "hello"}
        verifier = WebhookVerifier("global-secret")
        header = verifier.sign_header(payload)
        result = verify_webhook(payload, header)
        assert result["age_seconds"] >= 0

    def test_verify_webhook_without_configure(self):
        from src.common.webhook import default_verifier, verify_webhook
        assert default_verifier is None
        with pytest.raises(RuntimeError, match="not configured"):
            verify_webhook({"msg": "x"}, "t=...;s=...")


class TestDefaultReplayWindow:
    """Verify the default constant."""

    def test_default_window(self):
        assert DEFAULT_REPLAY_WINDOW_SECONDS == 300
