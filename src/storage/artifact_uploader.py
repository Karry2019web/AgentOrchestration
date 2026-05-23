"""Artifact Uploader — Manages large artifact uploads with lease renewal."""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

from src.common.metrics import metrics

logger = logging.getLogger(__name__)


class ArtifactUploader:
    def __init__(self, lease_manager, chunk_ttl: float = 120.0):
        self._lease_manager = lease_manager
        self.chunk_ttl = chunk_ttl
        self._uploads: Dict[str, Dict[str, Any]] = {}

    async def upload(
        self,
        job_id: str,
        artifact_data: bytes,
        upload_fn: Callable,
        chunk_size: int = 1024 * 1024,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        if not self._lease_manager.is_active(job_id):
            raise RuntimeError(f"Cannot upload artifact: job {job_id} has no active lease")

        self._lease_manager.mark_uploading(job_id)
        upload_id = f"upload_{job_id}_{int(time.time())}"
        self._uploads[upload_id] = {
            "job_id": job_id,
            "status": "in_progress",
            "total_size": len(artifact_data),
            "uploaded": 0,
            "started_at": time.time(),
        }
        metrics.gauge("artifact.upload.size", len(artifact_data))

        try:
            offset = 0
            while offset < len(artifact_data):
                chunk = artifact_data[offset : offset + chunk_size]
                chunk_meta = {
                    "job_id": job_id,
                    "upload_id": upload_id,
                    "offset": offset,
                    "total": len(artifact_data),
                }
                await upload_fn(chunk, chunk_meta)

                offset += len(chunk)
                self._uploads[upload_id]["uploaded"] = offset

                self._lease_manager.renew(job_id, ttl=self.chunk_ttl)
                metrics.increment("artifact.upload.chunk")
                metrics.gauge("artifact.upload.progress", offset / len(artifact_data) * 100)

            self._uploads[upload_id]["status"] = "completed"
            self._uploads[upload_id]["completed_at"] = time.time()
            metrics.increment("artifact.upload.completed")
            logger.info(f"Artifact upload {upload_id} completed ({len(artifact_data)} bytes)")

            return {
                "upload_id": upload_id,
                "job_id": job_id,
                "status": "completed",
                "size": len(artifact_data),
                "duration": time.time() - self._uploads[upload_id]["started_at"],
            }

        except Exception as e:
            self._uploads[upload_id]["status"] = "failed"
            self._uploads[upload_id]["error"] = str(e)
            metrics.increment("artifact.upload.failed")
            logger.error(f"Artifact upload {upload_id} failed: {e}")
            raise

    def get_upload_status(self, upload_id: str) -> Optional[Dict]:
        return self._uploads.get(upload_id)

    def get_active_uploads(self, job_id: Optional[str] = None) -> list:
        if job_id:
            return [
                u for u in self._uploads.values()
                if u.get("job_id") == job_id and u["status"] == "in_progress"
            ]
        return [u for u in self._uploads.values() if u["status"] == "in_progress"]

    def cleanup_old_uploads(self, max_age: float = 3600) -> int:
        now = time.time()
        stale = [
            uid for uid, u in self._uploads.items()
            if now - u.get("started_at", 0) > max_age
        ]
        for uid in stale:
            del self._uploads[uid]
        return len(stale)

# 2020-01-10T10:00:02 update
