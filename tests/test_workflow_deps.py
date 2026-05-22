"""Tests for workflow dependency parser — normalized identifiers."""

import pytest
from src.orchestrator.workflow import (
    DependencyIdentifier,
    WorkflowDependency,
    WorkflowDependencyParser,
    Workflow,
    WorkflowManager,
)


class TestDependencyIdentifier:
    def test_case_insensitive_equality(self):
        a = DependencyIdentifier("MyService")
        b = DependencyIdentifier("myservice")
        assert a == b

    def test_case_insensitive_equality_with_string(self):
        a = DependencyIdentifier("MyService")
        assert a == "myservice"
        assert a == "MYSERVICE"

    def test_preserves_raw_name(self):
        dep = DependencyIdentifier("MyCoolService")
        assert dep.raw == "MyCoolService"

    def test_different_names_not_equal(self):
        a = DependencyIdentifier("ServiceA")
        b = DependencyIdentifier("ServiceB")
        assert a != b

    def test_hash_consistency(self):
        a = DependencyIdentifier("MyService")
        b = DependencyIdentifier("myservice")
        assert hash(a) == hash(b)


class TestWorkflowDependency:
    def test_create_dependency(self):
        dep = WorkflowDependency("Database", ">=1.0")
        assert dep.name == "Database"
        assert dep.version == ">=1.0"
        assert dep.resolved is False

    def test_default_version(self):
        dep = WorkflowDependency("Redis")
        assert dep.version == "*"

    def test_normalized_id(self):
        dep = WorkflowDependency("MY_SERVICE")
        assert dep.id._normalized == "my_service"


class TestWorkflowDependencyParser:
    def setup_method(self):
        self.parser = WorkflowDependencyParser()

    def test_add_dependency(self):
        dep = self.parser.add_dependency("MyService", "1.0")
        assert dep.name == "MyService"
        assert self.parser.get_dependency("myservice") is dep

    def test_case_insensitive_lookup(self):
        self.parser.add_dependency("MyService")
        assert self.parser.get_dependency("MYSERVICE") is not None
        assert self.parser.get_dependency("myservice") is not None

    def test_rejects_duplicate_normalized(self):
        self.parser.add_dependency("MyService")
        with pytest.raises(ValueError, match="identifier conflict"):
            self.parser.add_dependency("myservice")

    def test_rejects_case_variant_duplicate(self):
        self.parser.add_dependency("DATABASE")
        with pytest.raises(ValueError, match="identifier conflict"):
            self.parser.add_dependency("database")

    def test_accepts_distinct_normalized_names(self):
        self.parser.add_dependency("ServiceA")
        self.parser.add_dependency("ServiceB")  # should not raise
        assert len(self.parser.list_dependencies()) == 2

    def test_list_dependencies_sorted(self):
        self.parser.add_dependency("Zervice")
        self.parser.add_dependency("Aservice")
        deps = self.parser.list_dependencies()
        assert deps[0].name == "Aservice"
        assert deps[1].name == "Zervice"

    def test_resolve_all_marks_all_resolved(self):
        dep1 = self.parser.add_dependency("A")
        dep2 = self.parser.add_dependency("B")
        assert dep1.resolved is False
        assert dep2.resolved is False
        self.parser.resolve_all()
        assert dep1.resolved is True
        assert dep2.resolved is True

    def test_validate_no_duplicates_passes_unique(self):
        self.parser.validate_no_duplicates(["A", "B", "C"])

    def test_validate_no_duplicates_rejects_case_duplicates(self):
        with pytest.raises(ValueError, match="Duplicate"):
            self.parser.validate_no_duplicates(["ServiceA", "servicea"])

    def test_get_unknown_returns_none(self):
        assert self.parser.get_dependency("nonexistent") is None


class TestWorkflowDependencyIntegration:
    def test_workflow_add_dependency(self):
        workflow = Workflow("test")
        dep = workflow.add_dependency("Database", ">=2.0")
        assert dep.name == "Database"
        assert workflow.dependency_parser.get_dependency("database") is dep

    def test_workflow_rejects_duplicate_dependency(self):
        workflow = Workflow("test")
        workflow.add_dependency("MyDB")
        with pytest.raises(ValueError, match="identifier conflict"):
            workflow.add_dependency("mydb")

    def test_validate_dependencies_resolves_all(self):
        workflow = Workflow("test")
        dep = workflow.add_dependency("MyDB")
        assert dep.resolved is False
        workflow.validate_dependencies()
        assert dep.resolved is True

    def test_workflow_execution_with_deps(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        workflow.add_dependency("MyDB")
        from unittest.mock import MagicMock
        step = MagicMock()
        step.name = "step1"
        step.handler.return_value = "done"
        workflow.add_step(step)

        wf_id = manager.create_workflow("test").id
        # The above creates a new workflow, use the one we configured
        manager._workflows[workflow.id] = workflow
        result = manager.execute_workflow(workflow.id)
        assert result is True
