"""Request ID context propagation for observability.

Uses threading.local instead of contextvars for broader compatibility.
Automatically propagates the request ID to background tasks so all
logs from a single request trace share the same correlation ID.
"""

import logging
import re
import threading
import uuid
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REQUEST_ID_HEADER = "X-Request-ID"


class _RequestIdContext(threading.local):
    """Thread-local request ID storage."""

    def __init__(self) -> None:
        self._id: str = "-"

    @property
    def current(self) -> str:
        return self._id

    @current.setter
    def current(self, value: str) -> None:
        self._id = value


_request_ctx = _RequestIdContext()


def get_request_id() -> str:
    """Return the current request ID (or '-' outside a request)."""
    return _request_ctx.current


def sanitize_request_id(value: Optional[str]) -> str:
    """Sanitize or generate a request ID.

    If *value* matches the allowed pattern it is returned as-is.
    Otherwise a random hex string is generated.
    """
    if value and _VALID_REQUEST_ID.fullmatch(value.strip()):
        return value.strip()
    return uuid.uuid4().hex


@contextmanager
def request_id_context(request_id: str) -> str:
    """Context manager that sets a request ID for the current thread.

    The previous value is restored on exit so that nested or parent
    scopes remain clean.
    """
    previous = _request_ctx.current
    _request_ctx.current = request_id
    try:
        yield request_id
    finally:
        _request_ctx.current = previous


class RequestIDLogFilter(logging.Filter):
    """Log filter that injects ``request_id`` into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


def install_request_id_filters() -> None:
    """Install :class:`RequestIDLogFilter` on all root handlers once."""
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_ao_request_id_filter_installed", False):
            continue
        handler.addFilter(RequestIDLogFilter())
        handler._ao_request_id_filter_installed = True


class BackgroundTaskWrapper:
    """Wrapper that propagates the current request ID into a background task.

    Usage::

        background_tasks.add_task(
            BackgroundTaskWrapper(request_id, some_fn, arg1, arg2)
        )
    """

    def __init__(self, request_id: str, fn, *args, **kwargs):
        self._request_id = request_id
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def __call__(self):
        with request_id_context(self._request_id):
            self._fn(*self._args, **self._kwargs)
