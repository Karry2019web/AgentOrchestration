import pytest
from src.orchestrator.workflow import (
    parse_duration,
    validate_timeout_unit_consistency,
    DurationParseError,
    WorkflowStep,
    Workflow,
    WorkflowManager,
)


class TestDurationParser:
    def test_parse_integer(self):
        assert parse_duration(300) == 300
        assert parse_duration(0) == 0

    def test_parse_float(self):
        assert parse_duration(30.0) == 30

    def test_parse_seconds_string(self):
        assert parse_duration("300") == 300
        assert parse_duration("0") == 0

    def test_parse_seconds_unit(self):
        assert parse_duration("30s") == 30
        assert parse_duration("30sec") == 30
        assert parse_duration("30secs") == 30
        assert parse_duration("30second") == 30
        assert parse_duration("30seconds") == 30

    def test_parse_minutes(self):
        assert parse_duration("5m") == 300
        assert parse_duration("5min") == 300
        assert parse_duration("5mins") == 300
        assert parse_duration("5minutes") == 300

    def test_parse_hours(self):
        assert parse_duration("2h") == 7200
        assert parse_duration("2hr") == 7200
        assert parse_duration("2hours") == 7200

    def test_parse_days(self):
        assert parse_duration("1d") == 86400
        assert parse_duration("1day") == 86400

    def test_parse_mixed_case(self):
        assert parse_duration("5M") == 300
        assert parse_duration("2H") == 7200
        assert parse_duration("1D") == 86400

    def test_parse_decimal(self):
        assert parse_duration("1.5m") == 90
        assert parse_duration("0.5h") == 1800

    def test_negative_duration(self):
        with pytest.raises(DurationParseError, match="Negative"):
            parse_duration(-1)
        with pytest.raises(DurationParseError, match="Negative"):
            parse_duration("-5")
        with pytest.raises(DurationParseError, match="Negative"):
            parse_duration("-1m")

    def test_empty_string(self):
        with pytest.raises(DurationParseError, match="empty"):
            parse_duration("")
        with pytest.raises(DurationParseError, match="empty"):
            parse_duration("   ")

    def test_unrecognized_format(self):
        with pytest.raises(DurationParseError, match="Unrecognized"):
            parse_duration("5xyz")
        with pytest.raises(DurationParseError, match="Unrecognized"):
            parse_duration("abc")

    def test_invalid_type(self):
        with pytest.raises(DurationParseError, match="Unsupported"):
            parse_duration(None)  # type: ignore
        with pytest.raises(DurationParseError, match="Unsupported"):
            parse_duration([])  # type: ignore


class TestTimeoutUnitConsistency:
    def test_single_unit_no_error(self):
        validate_timeout_unit_consistency("5m")
        validate_timeout_unit_consistency("30s")
        validate_timeout_unit_consistency("2h")

    def test_mixed_units_raises_error(self):
        with pytest.raises(DurationParseError, match="Conflicting"):
            validate_timeout_unit_consistency("5m", "30s")

    def test_numeric_exempt_from_check(self):
        validate_timeout_unit_consistency("5m", 300)
        validate_timeout_unit_consistency(300, 600)


class TestWorkflowStepTimeout:
    def test_timeout_default(self):
        def handler():
            pass

        step = WorkflowStep("test", handler)
        assert step.timeout == 300

    def test_timeout_in_seconds(self):
        def handler():
            pass

        step = WorkflowStep("test", handler, timeout="5m")
        assert step.timeout == 300

    def test_timeout_as_integer(self):
        def handler():
            pass

        step = WorkflowStep("test", handler, timeout=600)
        assert step.timeout == 600

    def test_invalid_timeout_raises(self):
        def handler():
            pass

        with pytest.raises(DurationParseError):
            WorkflowStep("test", handler, timeout="invalid")


class TestWorkflowManager:
    def test_create_workflow(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test")
        assert wf.name == "test"
        assert wf.id is not None

    def test_get_workflow(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test")
        assert mgr.get_workflow(wf.id) is wf

    def test_execute_workflow_success(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test")

        def handler():
            return "ok"

        wf.add_step(WorkflowStep("step1", handler))
        result = mgr.execute_workflow(wf.id)
        assert result is True

    def test_execute_workflow_failure(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test")

        def handler():
            raise ValueError("fail")

        wf.add_step(WorkflowStep("step1", handler))
        result = mgr.execute_workflow(wf.id)
        assert result is False
