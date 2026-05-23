"""Tests for request cancellation propagation."""

import asyncio
import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.common.cancellation import (
    CancellationScope,
    RequestCancellationContext,
    current_scope,
    run_with_cancellation,
)
from src.api.middleware import CancellationAwareMiddleware


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _request(headers=None):
    raw_headers = [
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": raw_headers,
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        },
        _receive,
    )


def _middleware():
    return CancellationAwareMiddleware(app=lambda scope, receive, send: None)


@pytest.mark.asyncio
async def test_scope_normal_completion():
    async with CancellationScope():
        result = await asyncio.sleep(0, result="ok")
    assert result == "ok"


@pytest.mark.asyncio
async def test_scope_cancel_cancels_registered_tasks():
    async with CancellationScope() as scope:
        task = scope.create_task(asyncio.sleep(10))
        scope.cancel()
        await asyncio.sleep(0.01)
        assert task.cancelled()


@pytest.mark.asyncio
async def test_scope_cancelled_property():
    scope = CancellationScope()
    assert not scope.cancelled
    scope.cancel()
    assert scope.cancelled


@pytest.mark.asyncio
async def test_scope_create_task_outside_context():
    scope = CancellationScope()
    task = scope.create_task(asyncio.sleep(0))
    result = await task
    assert result is None


@pytest.mark.asyncio
async def test_scope_cancel_before_task_starts():
    scope = CancellationScope()
    scope.cancel()
    async with scope:
        with pytest.raises(asyncio.CancelledError):
            await scope.create_task(asyncio.sleep(0))


@pytest.mark.asyncio
async def test_nested_scope_parent_cancellation_propagates():
    async with CancellationScope() as parent:
        child_result = []
        async def child_work():
            async with CancellationScope() as child:
                child.create_task(asyncio.sleep(10))
                await asyncio.sleep(0.1)
                child_result.append("done")
        parent.create_task(child_work())
        await asyncio.sleep(0.05)
        parent.cancel()
        await asyncio.sleep(0.05)
    assert child_result == []


@pytest.mark.asyncio
async def test_run_with_cancellation_timeout():
    with pytest.raises(asyncio.TimeoutError):
        await run_with_cancellation(asyncio.sleep(10), timeout=0.05)


@pytest.mark.asyncio
async def test_run_with_cancellation_completes_in_time():
    result = await run_with_cancellation(asyncio.sleep(0.01, result="done"), timeout=5)
    assert result == "done"


@pytest.mark.asyncio
async def test_current_scope_outside():
    assert current_scope() is None


@pytest.mark.asyncio
async def test_current_scope_inside():
    async with CancellationScope() as scope:
        assert current_scope() is scope


@pytest.mark.asyncio
async def test_request_context_normal():
    ctx = RequestCancellationContext()
    task = ctx.register_task(asyncio.sleep(0, result="ok"))
    result = await task
    assert result == "ok"
    assert not ctx.cancelled
    assert ctx.active_task_count == 0


@pytest.mark.asyncio
async def test_request_context_cancel():
    ctx = RequestCancellationContext()
    task = ctx.register_task(asyncio.sleep(10))
    ctx.cancel()
    await asyncio.sleep(0.01)
    assert task.cancelled()
    assert ctx.cancelled


@pytest.mark.asyncio
async def test_middleware_normal_request():
    request = _request()
    async def call_next(_req):
        assert hasattr(_req.state, "cancel_ctx")
        return Response(status_code=204)
    response = await _middleware().dispatch(request, call_next)
    assert response.status_code == 204
    assert response.headers.get("X-Agent-Cancellation") == "none"


@pytest.mark.asyncio
async def test_middleware_downstream_task_cancelled():
    request = _request()
    task_ref = []
    async def call_next(_req):
        ctx = _req.state.cancel_ctx
        task = ctx.register_task(asyncio.sleep(10))
        task_ref.append(task)
        ctx.cancel()
        return Response(status_code=204)
    response = await _middleware().dispatch(request, call_next)
    assert response.status_code == 499
    assert response.headers.get("X-Agent-Cancellation") == "propagated"


@pytest.mark.asyncio
async def test_middleware_task_count_header():
    request = _request()
    async def call_next(_req):
        ctx = _req.state.cancel_ctx
        ctx.register_task(asyncio.sleep(0.01))
        await asyncio.sleep(0.02)
        return Response(status_code=200)
    response = await _middleware().dispatch(request, call_next)
    assert response.status_code == 200
    assert response.headers.get("X-Agent-Downstream-Tasks") == "0"
