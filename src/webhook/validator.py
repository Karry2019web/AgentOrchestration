"""Webhook Endpoint Validation.

Validates webhook endpoints to prevent unsafe targets like localhost
unless explicitly allowed via configuration.
"""

import re
import logging
from typing import Optional
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Standard loopback addresses
LOCALHOST_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
LOCALHOST_PATTERNS = [
    re.compile(r"^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    re.compile(r"^0\.0\.0\.0$"),
    re.compile(r"^::$"),
    re.compile(r"^::1$"),
    re.compile(r"^localhost$", re.IGNORECASE),
]


@dataclass
class WebhookEndpoint:
    url: str
    allowed: bool = False
    error: Optional[str] = None


@dataclass
class WebhookConfig:
    allow_localhost: bool = False
    allowed_localhost_targets: set = field(default_factory=set)


_default_config = WebhookConfig()


def is_localhost(url: str) -> bool:
    """Check if a URL targets a localhost/loopback address.

    Args:
        url: The webhook endpoint URL to validate.

    Returns:
        True if the URL targets a localhost address.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        return False

    if hostname.lower() in LOCALHOST_HOSTNAMES:
        return True

    for pattern in LOCALHOST_PATTERNS:
        if pattern.match(hostname):
            return True

    return False


def validate_endpoint(
    url: str,
    config: Optional[WebhookConfig] = None,
) -> WebhookEndpoint:
    """Validate a webhook endpoint URL.

    Rejects localhost targets unless explicitly allowed via config.

    Args:
        url: The webhook endpoint URL to validate.
        config: Optional configuration for allowed endpoints.

    Returns:
        WebhookEndpoint with validation result.
    """
    cfg = config or _default_config

    if not url or not url.strip():
        return WebhookEndpoint(url=url, allowed=False, error="URL is empty")

    try:
        parsed = urlparse(url)
    except Exception as e:
        return WebhookEndpoint(url=url, allowed=False, error=f"Invalid URL: {e}")

    if not parsed.scheme:
        return WebhookEndpoint(url=url, allowed=False, error="URL must have a scheme (http or https)")

    if parsed.scheme not in ("http", "https"):
        return WebhookEndpoint(
            url=url, allowed=False, error=f"Unsupported scheme: {parsed.scheme}"
        )

    hostname = parsed.hostname or ""

    if not hostname:
        return WebhookEndpoint(url=url, allowed=False, error="URL has no hostname")

    if is_localhost(url):
        if cfg.allow_localhost or hostname in cfg.allowed_localhost_targets:
            return WebhookEndpoint(url=url, allowed=True)
        return WebhookEndpoint(
            url=url,
            allowed=False,
            error=f"Localhost target '{hostname}' is not allowed. "
                  f"Set allow_localhost=True or add '{hostname}' to allowed_localhost_targets.",
        )

    return WebhookEndpoint(url=url, allowed=True)


def configure_webhook(
    allow_localhost: bool = False,
    allowed_localhost_targets: Optional[set] = None,
) -> WebhookConfig:
    """Configure webhook validation settings globally.

    Args:
        allow_localhost: If True, localhost targets are allowed.
        allowed_localhost_targets: Set of specific localhost addresses to allow.

    Returns:
        The global WebhookConfig instance.
    """
    global _default_config
    _default_config = WebhookConfig(
        allow_localhost=allow_localhost,
        allowed_localhost_targets=allowed_localhost_targets or set(),
    )
    return _default_config
