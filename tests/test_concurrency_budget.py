"""Tests for concurrency budgeting in manually triggered runs."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.orchestrator.engine import ConcurrencyBudgetManager


class TestConcurrencyBudgetManager:
    def setup_method(self):
        self.budget = ConcurrencyBudgetManager(max_concurrent_runs=5, max_per_agent=2)

    def test_acquire_within_limit(self):
        assert self.budget.acquire("run-1", "agent-1") is True
        assert self.budget.get_active_count() == 1

    def test_acquire_exceeds_limit(self):
        for i in range(5):
            assert self.budget.acquire(f"run-{i}", f"agent-{i}") is True
        assert self.budget.acquire("run-over", "agent-over") is False

    def test_acquire_exceeds_per_agent(self):
        assert self.budget.acquire("run-1", "agent-a") is True
        assert self.budget.acquire("run-2", "agent-a") is True
        assert self.budget.acquire("run-3", "agent-a") is False  # max_per_agent=2

    def test_release_frees_capacity(self):
        assert self.budget.acquire("run-1", "agent-1") is True
        assert self.budget.get_active_count() == 1
        self.budget.release("run-1")
        assert self.budget.get_active_count() == 0

    def test_release_for_agent(self):
        assert self.budget.acquire("run-1", "agent-a") is True
        assert self.budget.get_agent_count("agent-a") == 1
        self.budget.release_for_agent("run-1", "agent-a")
        assert self.budget.get_agent_count("agent-a") == 0

    def test_manual_run_accounting(self):
        self.budget.acquire("run-m", "agent-1", is_manual=True)
        assert self.budget.get_manual_run_count() == 1
        self.budget.release("run-m")
        assert self.budget.get_manual_run_count() == 0

    def test_blocked_runs_tracked(self):
        tiny = ConcurrencyBudgetManager(max_concurrent_runs=1, max_per_agent=1)
        tiny.acquire("run-1", "agent-1")
        tiny.acquire("run-2", "agent-2")
        blocked = tiny.get_blocked_runs()
        assert len(blocked) == 1
        assert blocked[0]["reason"] == "concurrency_limit"

    def test_to_dict(self):
        self.budget.acquire("run-1", "agent-1")
        d = self.budget.to_dict()
        assert d["active_runs"] == 1
        assert d["max_concurrent"] == 5
        assert d["max_per_agent"] == 2

    def test_multiple_agents_independent(self):
        self.budget.acquire("r1", "agent-a")
        self.budget.acquire("r2", "agent-a")
        self.budget.acquire("r3", "agent-b")
        assert self.budget.get_agent_count("agent-a") == 2
        assert self.budget.get_agent_count("agent-b") == 1
