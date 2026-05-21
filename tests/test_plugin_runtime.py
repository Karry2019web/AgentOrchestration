"""Tests for PluginRuntime manifest validation and hook loading."""
import sys
from unittest.mock import MagicMock

# Mock platform-specific / missing deps BEFORE any src import
sys.modules["resource"] = MagicMock()

# AgentStatus exists in registry.py but is not exported by __init__.py
# Mock it so engine.py can import it
import src.agent
src.agent.AgentStatus = MagicMock()
src.agent.AgentRegistry = MagicMock()

# Now safe to import
from src.orchestrator.plugin_runtime import (
    PluginRuntime,
    ManifestState,
    validate_manifest,
)


def _manifest(plugin_id="test-plugin", hook_event="pre_execute", **overrides):
    m = {
        "id": plugin_id,
        "version": "1.0.0",
        "hooks": [
            {"id": "my-hook", "event": hook_event, "callback": "test_plugin_runtime:dummy_callback"}
        ],
    }
    m.update(overrides)
    return m


def dummy_callback(*args, **kwargs):
    return None


# ------------------------------------------------------------------
# Schema validation tests
# ------------------------------------------------------------------

def test_valid_manifest_passes_validation():
    assert validate_manifest(_manifest()) == []


def test_missing_id_is_rejected():
    m = _manifest()
    del m["id"]
    errors = validate_manifest(m)
    assert any("missing required field 'id'" in e for e in errors)


def test_unsupported_hook_event_is_rejected():
    errors = validate_manifest(_manifest(hook_event="before_everything"))
    assert any("not allowed" in e.lower() for e in errors)


def test_hook_without_callback_is_rejected():
    m = _manifest()
    m["hooks"][0].pop("callback")
    errors = validate_manifest(m)
    assert any("missing required field 'callback'" in e for e in errors)


def test_hooks_must_be_list():
    m = _manifest()
    m["hooks"] = "not-a-list"
    errors = validate_manifest(m)
    assert any("must be a list" in e for e in errors)


# ------------------------------------------------------------------
# Runtime integration tests (with mock engine)
# ------------------------------------------------------------------

def _make_runtime():
    engine = MagicMock()
    engine._hooks = {"pre_execute": [], "post_execute": [], "on_error": [], "on_complete": []}
    engine.register_hook.side_effect = lambda event, cb: engine._hooks[event].append(cb)
    return engine, PluginRuntime(engine)


def test_invalid_manifest_rejected_before_hooks_loaded():
    engine, runtime = _make_runtime()
    loaded = runtime.load_manifest(_manifest(hook_event="invalid_event"))
    record = runtime.get_record("test-plugin")
    assert loaded is False
    assert record.state == ManifestState.INVALID
    assert engine._hooks["pre_execute"] == []


def test_valid_manifest_loads_hooks():
    engine, runtime = _make_runtime()
    loaded = runtime.load_manifest(_manifest())
    record = runtime.get_record("test-plugin")
    assert loaded is True
    assert record.state == ManifestState.LOADED
    assert len(engine._hooks["pre_execute"]) == 1


def test_multiple_hooks_on_different_events():
    engine, runtime = _make_runtime()
    m = {
        "id": "multi-hook",
        "version": "2.0.0",
        "hooks": [
            {"id": "h1", "event": "pre_execute", "callback": "a_module:dummy"},
            {"id": "h2", "event": "post_execute", "callback": "a_module:dummy"},
        ],
    }
    assert runtime.load_manifest(m)
    assert len(engine._hooks["pre_execute"]) == 1
    assert len(engine._hooks["post_execute"]) == 1


def test_empty_hooks_list_is_valid():
    engine, runtime = _make_runtime()
    assert runtime.load_manifest({"id": "no-hooks", "version": "1.0.0", "hooks": []})


def test_attempt_count_tracks_retries():
    engine, runtime = _make_runtime()
    runtime.load_manifest(_manifest(hook_event="bad"))
    assert runtime.get_record("test-plugin").attempt_count == 1
    runtime.load_manifest(_manifest(hook_event="bad"))
    assert runtime.get_record("test-plugin").attempt_count == 2


def test_duplicate_plugin_id():
    engine, runtime = _make_runtime()
    runtime.load_manifest(_manifest(plugin_id="dup"))
    runtime.load_manifest(_manifest(plugin_id="dup"))
    assert list(runtime._records.keys()) == ["dup"]


def test_validate_helper():
    engine, runtime = _make_runtime()
    v, e = runtime.validate(_manifest())
    assert v is True and e == []
    v, e = runtime.validate(_manifest(hook_event="bad"))
    assert v is False and len(e) > 0


def test_concurrent_load_is_safe():
    import threading
    engine, runtime = _make_runtime()
    results = []
    def try_load():
        results.append(runtime.load_manifest(_manifest(plugin_id="concurrent")))
    threads = [threading.Thread(target=try_load) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert any(results)
    assert runtime.get_record("concurrent").attempt_count >= 1
