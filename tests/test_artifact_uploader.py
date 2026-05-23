import pytest
import time
from src.storage.lease_manager import JobLeaseManager
from src.storage.artifact_uploader import ArtifactUploader


class TestArtifactUploader:
    def setup_method(self):
        self.lm = JobLeaseManager(default_ttl=60.0)
        self.uploader = ArtifactUploader(self.lm, chunk_ttl=120.0)

    @pytest.mark.asyncio
    async def test_upload_no_lease_raises(self):
        async def fake_upload(chunk, meta):
            pass
        with pytest.raises(RuntimeError, match="no active lease"):
            await self.uploader.upload("no-job", b"data", fake_upload)

    @pytest.mark.asyncio
    async def test_upload_small_artifact(self):
        self.lm.acquire("job-1")
        uploaded_chunks = []

        async def capture_chunk(chunk, meta):
            uploaded_chunks.append((chunk, meta))

        result = await self.uploader.upload(
            "job-1", b"hello-world", capture_chunk, chunk_size=1024
        )
        assert result["status"] == "completed"
        assert result["job_id"] == "job-1"
        assert result["size"] == 11
        assert len(uploaded_chunks) == 1

    @pytest.mark.asyncio
    async def test_upload_large_artifact(self):
        self.lm.acquire("job-2")
        data = b"x" * (1024 * 5)
        chunks = []

        async def capture_chunk(chunk, meta):
            chunks.append(chunk)

        result = await self.uploader.upload("job-2", data, capture_chunk, chunk_size=1024)
        assert result["status"] == "completed"
        assert result["size"] == 1024 * 5
        assert len(chunks) == 5

    def test_get_upload_status(self):
        assert self.uploader.get_upload_status("nonexistent") is None

# 2020-01-10T10:00:05 update
