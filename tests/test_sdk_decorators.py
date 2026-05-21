"""Tests for SDK decorators — sync task function handling."""
import asyncio
import pytest
from src.sdk.decorators import task


class TestSDKDecorators:
    """Regression suite for sync/async task decorator behavior."""

    @pytest.mark.asyncio
    async def test_async_task_returns_value(self):
        """An async decorated task executes and returns the expected value."""
        @task(name="async_add")
        async def add(a: int, b: int) -> int:
            return a + b

        result = await add(10, 20)
        assert result == 30

    @pytest.mark.asyncio
    async def test_sync_task_returns_value(self):
        """A sync decorated task executes and returns the expected value."""
        @task(name="sync_multiply")
        def multiply(a: int, b: int) -> int:
            return a * b

        result = await multiply(6, 7)
        assert result == 42

    @pytest.mark.asyncio
    async def test_sync_task_with_strings(self):
        """Sync task with string arguments works correctly."""
        @task(name="sync_greet")
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        result = await greet("World")
        assert result == "Hello, World!"

    @pytest.mark.asyncio
    async def test_async_task_timeout(self):
        """An async task that exceeds the timeout raises TimeoutError."""
        @task(name="slow_async", timeout=0.01)
        async def slow():
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError, match="slow_async timed out after"):
            await slow()

    @pytest.mark.asyncio
    async def test_sync_task_timeout(self):
        """A sync task that exceeds the timeout raises TimeoutError."""
        @task(name="slow_sync", timeout=0.01)
        def slow():
            import time
            time.sleep(10)

        with pytest.raises(TimeoutError, match="slow_sync timed out after"):
            await slow()

    def test_task_config_set_on_async_function(self):
        """Task config metadata on decorated async functions."""
        @task(name="cfg_async", retries=3, timeout=60)
        async def sample():
            pass

        assert sample.__task_config__ == {
            "name": "cfg_async",
            "retries": 3,
            "timeout": 60,
        }

    def test_task_config_set_on_sync_function(self):
        """Task config metadata on decorated sync functions."""
        @task(name="cfg_sync", retries=2, timeout=30)
        def sample():
            pass

        assert sample.__task_config__ == {
            "name": "cfg_sync",
            "retries": 2,
            "timeout": 30,
        }

    def test_task_config_default_name_from_function(self):
        """When no name is provided, __task_config__ uses the function name."""
        @task()
        async def my_custom_name():
            pass

        assert my_custom_name.__task_config__["name"] == "my_custom_name"

    @pytest.mark.asyncio
    async def test_sync_task_returns_none(self):
        """Sync task that returns None handles correctly."""
        @task(name="returns_none")
        def do_nothing():
            pass

        result = await do_nothing()
        assert result is None

    @pytest.mark.asyncio
    async def test_async_task_returns_none(self):
        """Async task that returns None correctly."""
        @task(name="async_none")
        async def do_nothing():
            pass

        result = await do_nothing()
        assert result is None

    @pytest.mark.asyncio
    async def test_task_config_defaults(self):
        """Default retries and timeout values are set correctly."""
        @task()
        async def default_task():
            pass

        assert default_task.__task_config__["retries"] == 0
        assert default_task.__task_config__["timeout"] == 300
