"""Job Lease Manager — Prevents duplicate task execution during long operations."""

import logging
import time
from enum import Enum
from typing import Dict, Optional, Set

from src.common.metrics import metrics

logger = logging.getLogger(__name__)


class LeaseState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    EXPIRED = "expired"


class JobLeaseManager:
    def __init__(self, default_ttl: float = 60.0, upload_ttl: float = 600.0):
        self.default_ttl = default_ttl
        self.upload_ttl = upload_ttl
        self._leases: Dict[str, LeaseState] = {}
        self._expirations: Dict[str, float] = {}
        self._uploading: Set[str] = set()

    def acquire(self, job_id: str, ttl: Optional[float] = None) -> bool:
        now = time.time()
        if job_id in self._leases:
            if self._expirations.get(job_id, 0) > now:
                logger.warning(f"Job {job_id} already has an active lease")
                return False
            self._leases.pop(job_id, None)
            self._expirations.pop(job_id, None)

        expiry = now + (ttl or self.default_ttl)
        self._leases[job_id] = LeaseState.RUNNING
        self._expirations[job_id] = expiry
        metrics.increment("job.lease.acquired")
        logger.info(f"Acquired lease for job {job_id} (expires in {ttl or self.default_ttl}s)")
        return True

    def renew(self, job_id: str, ttl: Optional[float] = None) -> bool:
        now = time.time()
        if job_id not in self._leases:
            logger.warning(f"Cannot renew lease for unknown job {job_id}")
            return False
        if self._expirations.get(job_id, 0) <= now:
            logger.warning(f"Cannot renew expired lease for job {job_id}")
            return False

        new_expiry = now + (ttl or self.default_ttl)
        self._expirations[job_id] = new_expiry
        metrics.increment("job.lease.renewed")
        logger.info(f"Renewed lease for job {job_id} (extends to +{ttl or self.default_ttl}s)")
        return True

    def mark_uploading(self, job_id: str) -> bool:
        now = time.time()
        if job_id not in self._leases:
            logger.warning(f"Cannot mark unknown job {job_id} as uploading")
            return False
        if self._expirations.get(job_id, 0) <= now:
            logger.warning(f"Cannot mark expired job {job_id} as uploading")
            return False

        self._leases[job_id] = LeaseState.UPLOADING
        self._expirations[job_id] = now + self.upload_ttl
        self._uploading.add(job_id)
        metrics.increment("job.lease.uploading")
        logger.info(f"Job {job_id} marked as uploading (lease extended to +{self.upload_ttl}s)")
        return True

    def complete(self, job_id: str) -> bool:
        if job_id not in self._leases:
            return False
        self._leases[job_id] = LeaseState.COMPLETED
        self._uploading.discard(job_id)
        if job_id in self._expirations:
            del self._expirations[job_id]
        metrics.increment("job.lease.completed")
        logger.info(f"Job {job_id} lease completed and released")
        return True

    def release(self, job_id: str) -> bool:
        exists = job_id in self._leases
        self._leases.pop(job_id, None)
        self._expirations.pop(job_id, None)
        self._uploading.discard(job_id)
        if exists:
            metrics.increment("job.lease.released")
            logger.info(f"Job {job_id} lease released")
        return exists

    def is_active(self, job_id: str) -> bool:
        now = time.time()
        expiry = self._expirations.get(job_id, 0)
        return job_id in self._leases and expiry > now

    def is_expired(self, job_id: str) -> bool:
        now = time.time()
        expiry = self._expirations.get(job_id, 0)
        if job_id in self._leases and expiry <= now:
            self._leases[job_id] = LeaseState.EXPIRED
            self._uploading.discard(job_id)
            return True
        return False

    def get_state(self, job_id: str) -> Optional[LeaseState]:
        return self._leases.get(job_id)

    def get_expired(self) -> list:
        now = time.time()
        return [
            jid for jid, exp in self._expirations.items()
            if exp <= now and jid in self._leases
        ]

    def sweep_expired(self) -> int:
        expired = self.get_expired()
        for jid in expired:
            self._leases[jid] = LeaseState.EXPIRED
            self._uploading.discard(jid)
            metrics.increment("job.lease.expired")
            logger.info(f"Job {jid} lease expired during sweep")
        return len(expired)

    def is_uploading(self, job_id: str) -> bool:
        return job_id in self._uploading

    def active_count(self) -> int:
        now = time.time()
        return sum(1 for exp in self._expirations.values() if exp > now)

    def clear(self) -> None:
        self._leases.clear()
        self._expirations.clear()
        self._uploading.clear()

# 2020-01-10T10:00:01 update
