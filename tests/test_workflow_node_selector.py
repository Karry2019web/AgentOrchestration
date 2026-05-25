import pytest
from uuid import uuid4

from src.orchestrator.workflow import (
    NodeDependencyError,
    NodeDependencyValidator,
    StepStatus,
    Workflow,
    WorkflowManager,
    WorkflowNode,
    WorkflowStep,
)


class TestWorkflowNode:
    def test_node_creation(self):
        node = WorkflowNode(name="test-node", handler=lambda: "ok")
        assert node.name == "test-node"
        assert node.depends_on == []
        assert node.status == StepStatus.PENDING
        assert node.id is not None

    def test_node_with_depends(self):
        node = WorkflowNode(name="child", handler=lambda: "ok", depends_on=["parent"])
        assert node.depends_on == ["parent"]

    def test_node_default_status(self):
        node = WorkflowNode(name="root", handler=lambda: True)
        assert node.status == StepStatus.PENDING


class TestNodeDependencyValidator:
    def test_empty_list_is_valid(self):
        errors = NodeDependencyValidator.validate_nodes([])
        assert errors == []

    def test_single_node_is_valid(self):
        node = WorkflowNode(name="a", handler=lambda: None)
        errors = NodeDependencyValidator.validate_nodes([node])
        assert errors == []

    def test_explicit_dependency_is_valid(self):
        a = WorkflowNode(name="a", handler=lambda: None)
        b = WorkflowNode(name="b", handler=lambda: None, depends_on=["a"])
        errors = NodeDependencyValidator.validate_nodes([a, b])
        assert errors == []

    def test_missing_dependency_fails(self):
        a = WorkflowNode(name="a", handler=lambda: None)
        b = WorkflowNode(name="b", handler=lambda: None, depends_on=["nonexistent"])
        errors = NodeDependencyValidator.validate_nodes([a, b])
        assert any("unknown node" in e.lower() for e in errors)

    def test_duplicate_name_fails(self):
        a1 = WorkflowNode(name="dup", handler=lambda: None)
        a2 = WorkflowNode(name="dup", handler=lambda: None)
        errors = NodeDependencyValidator.validate_nodes([a1, a2])
        assert any("duplicate" in e.lower() for e in errors)

    def test_cycle_detected(self):
        a = WorkflowNode(name="a", handler=lambda: None, depends_on=["b"])
        b = WorkflowNode(name="b", handler=lambda: None, depends_on=["a"])
        errors = NodeDependencyValidator.validate_nodes([a, b])
        assert any("circular" in e.lower() for e in errors)

    def test_self_cycle_detected(self):
        a = WorkflowNode(name="a", handler=lambda: None, depends_on=["a"])
        errors = NodeDependencyValidator.validate_nodes([a])
        assert any("circular" in e.lower() for e in errors)

    def test_two_root_nodes_parallel_ok(self):
        a = WorkflowNode(name="fetch-users", handler=lambda: None)
        b = WorkflowNode(name="fetch-products", handler=lambda: None)
        errors = NodeDependencyValidator.validate_nodes([a, b])
        assert errors == []

    def test_diamond_dag_is_valid(self):
        start = WorkflowNode(name="start", handler=lambda: None)
        left = WorkflowNode(name="left", handler=lambda: None, depends_on=["start"])
        right = WorkflowNode(name="right", handler=lambda: None, depends_on=["start"])
        end = WorkflowNode(name="end", handler=lambda: None, depends_on=["left", "right"])
        errors = NodeDependencyValidator.validate_nodes([start, left, right, end])
        assert errors == []


class TestWorkflowWithDag:
    def test_add_node(self):
        wf = Workflow("test")
        node = WorkflowNode(name="step1", handler=lambda: "done")
        wf.add_node(node)
        assert len(wf.nodes) == 1
        assert wf.get_node("step1") is node

    def test_add_multiple_nodes(self):
        wf = Workflow("multi")
        wf.add_node(WorkflowNode(name="a", handler=lambda: None))
        wf.add_node(WorkflowNode(name="b", handler=lambda: None, depends_on=["a"]))
        assert len(wf.nodes) == 2

    def test_get_node_returns_none_for_missing(self):
        wf = Workflow("empty")
        assert wf.get_node("nonexistent") is None


class TestWorkflowManagerWithDag:
    def test_execute_single_node(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("single")
        results = []

        def handler():
            results.append("done")
            return "ok"

        wf.add_node(WorkflowNode(name="only", handler=handler))
        success = manager.execute_workflow(wf.id)
        assert success
        assert results == ["done"]
        assert wf.status == StepStatus.COMPLETED

    def test_execute_linear_chain(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("chain")
        order = []

        def make_handler(name):
            def handler():
                order.append(name)
                return name
            return handler

        a = WorkflowNode(name="a", handler=make_handler("a"))
        b = WorkflowNode(name="b", handler=make_handler("b"), depends_on=["a"])
        c = WorkflowNode(name="c", handler=make_handler("c"), depends_on=["b"])
        wf.add_node(a).add_node(b).add_node(c)

        success = manager.execute_workflow(wf.id)
        assert success
        assert order == ["a", "b", "c"]
        assert wf.status == StepStatus.COMPLETED

    def test_execute_parallel_roots(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("parallel")
        executed = set()

        def make_handler(name):
            def handler():
                executed.add(name)
                return name
            return handler

        a = WorkflowNode(name="fetch-a", handler=make_handler("fetch-a"))
        b = WorkflowNode(name="fetch-b", handler=make_handler("fetch-b"))
        c = WorkflowNode(name="fetch-c", handler=make_handler("fetch-c"))
        wf.add_node(a).add_node(b).add_node(c)

        success = manager.execute_workflow(wf.id)
        assert success
        # All three independent nodes execute
        assert executed == {"fetch-a", "fetch-b", "fetch-c"}
        assert wf.status == StepStatus.COMPLETED

    def test_execute_diamond_dag(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("diamond")
        order = []

        def make_handler(name):
            def handler():
                order.append(name)
                return name
            return handler

        start = WorkflowNode(name="start", handler=make_handler("start"))
        left = WorkflowNode(name="left", handler=make_handler("left"), depends_on=["start"])
        right = WorkflowNode(name="right", handler=make_handler("right"), depends_on=["start"])
        end = WorkflowNode(name="end", handler=make_handler("end"), depends_on=["left", "right"])
        wf.add_node(start).add_node(left).add_node(right).add_node(end)

        success = manager.execute_workflow(wf.id)
        assert success
        assert order[0] == "start"
        assert "left" in order and "right" in order
        assert order[-1] == "end"
        assert wf.status == StepStatus.COMPLETED

    def test_invalid_dependency_fails(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("invalid")
        a = WorkflowNode(name="a", handler=lambda: None)
        b = WorkflowNode(name="b", handler=lambda: None, depends_on=["nonexistent"])
        wf.add_node(a).add_node(b)
        success = manager.execute_workflow(wf.id)
        assert not success
        assert wf.status == StepStatus.FAILED

    def test_cycle_fails_validation(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("cycle")
        a = WorkflowNode(name="a", handler=lambda: None, depends_on=["b"])
        b = WorkflowNode(name="b", handler=lambda: None, depends_on=["a"])
        wf.add_node(a).add_node(b)
        success = manager.execute_workflow(wf.id)
        assert not success
        assert wf.status == StepStatus.FAILED

    def test_node_failure_stops_execution(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("fail")
        downstream_ran = []

        def fail_handler():
            raise ValueError("intentional failure")

        def downstream_handler():
            downstream_ran.append("should-not-run")

        a = WorkflowNode(name="fail-node", handler=fail_handler)
        b = WorkflowNode(name="downstream", handler=downstream_handler, depends_on=["fail-node"])
        wf.add_node(a).add_node(b)

        success = manager.execute_workflow(wf.id)
        assert not success
        assert downstream_ran == []
        assert wf.status == StepStatus.FAILED

    def test_legacy_steps_still_work(self):
        manager = WorkflowManager()
        wf = manager.create_workflow("legacy")
        results = []

        wf.add_step(WorkflowStep(name="s1", handler=lambda: results.append("s1")))
        wf.add_step(WorkflowStep(name="s2", handler=lambda: results.append("s2")))

        success = manager.execute_workflow(wf.id)
        assert success
        assert results == ["s1", "s2"]
        assert wf.status == StepStatus.COMPLETED
