"""Tests for SDK decorators."""

import pytest

from src.sdk.decorators import task


def test_task_decorator_rejects_negative_retries():
    with pytest.raises(ValueError, match="non-negative integer"):
        task(retries=-1)


def test_task_decorator_rejects_non_integer_retries():
    for invalid_retries in (1.5, "2", True):
        with pytest.raises(ValueError, match="non-negative integer"):
            task(retries=invalid_retries)  # type: ignore[arg-type]


def test_task_decorator_preserves_non_negative_retries():
    @task(retries=0)
    async def default_retry_task():
        return "ok"

    @task(retries=3)
    async def custom_retry_task():
        return "ok"

    default_retry_config = getattr(default_retry_task, "__task_config__")
    custom_retry_config = getattr(custom_retry_task, "__task_config__")

    assert default_retry_config["retries"] == 0
    assert custom_retry_config["retries"] == 3
