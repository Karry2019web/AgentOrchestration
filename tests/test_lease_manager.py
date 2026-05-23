import pytest
import time
from src.storage.lease_manager import JobLeaseManager, LeaseState


class TestJobLeaseManager:
    def setup_method(self):
        self.lm = JobLeaseManager(default_ttl=60.0, upload_ttl=600.0)

    def test_acquire_new_lease(self):
        assert self.lm.acquire("job-1")
        assert self.lm.is_active("job-1")
        assert self.lm.get_state("job-1") == LeaseState.RUNNING

    def test_acquire_duplicate_rejected(self):
        self.lm.acquire("job-1")
        assert not self.lm.acquire("job-1")

    def test_renew_lease(self):
        self.lm.acquire("job-1", ttl=1.0)
        assert self.lm.renew("job-1", ttl=60.0)
        assert self.lm.is_active("job-1")

    def test_renew_unknown_job(self):
        assert not self.lm.renew("nonexistent")

    def test_mark_uploading(self):
        self.lm.acquire("job-1")
        assert self.lm.mark_uploading("job-1")
        assert self.lm.is_uploading("job-1")
        assert self.lm.get_state("job-1") == LeaseState.UPLOADING

    def test_complete_lease(self):
        self.lm.acquire("job-1")
        assert self.lm.complete("job-1")
        assert not self.lm.is_active("job-1")
        assert self.lm.get_state("job-1") == LeaseState.COMPLETED

    def test_release_lease(self):
        self.lm.acquire("job-1")
        assert self.lm.release("job-1")
        assert not self.lm.is_active("job-1")

    def test_sweep_expired(self):
        self.lm = JobLeaseManager(default_ttl=-1.0)
        self.lm.acquire("job-1")
        assert self.lm.sweep_expired() == 1
        assert self.lm.get_state("job-1") == LeaseState.EXPIRED

    def test_active_count(self):
        assert self.lm.active_count() == 0
        self.lm.acquire("job-1")
        assert self.lm.active_count() == 1

    def test_expired_returns_false_for_operations(self):
        self.lm = JobLeaseManager(default_ttl=-1.0)
        self.lm.acquire("job-1")
        assert not self.lm.is_active("job-1")
        assert self.lm.is_expired("job-1")

    def test_clear_resets_all(self):
        self.lm.acquire("job-1")
        self.lm.acquire("job-2")
        self.lm.clear()
        assert self.lm.active_count() == 0
        assert not self.lm.is_active("job-1")

# 2020-01-10T10:00:04 update
