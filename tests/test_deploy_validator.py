"""Tests for the deploy module resource validator."""

from src.deploy.validator import (
    WorkerResourceValidator,
    WorkerManifest,
    ValidationError,
    _parse_cpu,
    _parse_memory,
    WORKER_CLASS_MINIMUMS,
)


class TestCPUParse:
    def test_millicores(self):
        assert _parse_cpu("500m") == 500
        assert _parse_cpu("250m") == 250
        assert _parse_cpu("1000m") == 1000

    def test_whole_cores(self):
        assert _parse_cpu("1") == 1000
        assert _parse_cpu("2") == 2000

    def test_decimal_cores(self):
        assert _parse_cpu("0.5") == 500
        assert _parse_cpu("1.5") == 1500


class TestMemoryParse:
    def test_mebibytes(self):
        assert _parse_memory("256Mi") == 256
        assert _parse_memory("512Mi") == 512

    def test_gibibytes(self):
        assert _parse_memory("1Gi") == 1024
        assert _parse_memory("2Gi") == 2048

    def test_megabytes(self):
        assert _parse_memory("256M") == 256

    def test_raw_bytes(self):
        assert _parse_memory("268435456") == 256


class TestWorkerManifestFromDict:
    def test_basic_parsing(self):
        data = {
            "name": "test-worker",
            "worker_class": "worker.processor",
            "resources": {
                "requests": {"cpu": "500m", "memory": "256Mi"},
                "limits": {"cpu": "1000m", "memory": "512Mi"},
            },
            "replicas": 2,
            "image": "my-image:latest",
            "env": {"FOO": "bar"},
        }
        manifest = WorkerManifest.from_dict(data)
        assert manifest.name == "test-worker"
        assert manifest.worker_class == "worker.processor"
        assert manifest.cpu_request == 500
        assert manifest.memory_request == 256
        assert manifest.cpu_limit == 1000
        assert manifest.memory_limit == 512
        assert manifest.replicas == 2
        assert manifest.image == "my-image:latest"
        assert manifest.env == {"FOO": "bar"}

    def test_minimal_parsing(self):
        data = {"name": "minimal", "worker_class": "worker.sink"}
        manifest = WorkerManifest.from_dict(data)
        assert manifest.name == "minimal"
        assert manifest.cpu_request is None
        assert manifest.memory_request is None
        assert manifest.replicas == 1


class TestWorkerResourceValidator:
    def setup_method(self):
        self.validator = WorkerResourceValidator()

    def test_valid_manifest(self):
        manifest = WorkerManifest(
            name="good-worker",
            worker_class="worker.processor",
            cpu_request=500,
            memory_request=256,
            image="image:v1",
        )
        self.validator.validate(manifest)

    def test_missing_cpu_request(self):
        manifest = WorkerManifest(
            name="no-cpu",
            worker_class="worker.processor",
            cpu_request=None,
            memory_request=256,
            image="image:v1",
        )
        import traceback
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "CPU request is missing" in str(e)

    def test_missing_memory_request(self):
        manifest = WorkerManifest(
            name="no-mem",
            worker_class="worker.processor",
            cpu_request=500,
            memory_request=None,
            image="image:v1",
        )
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "Memory request is missing" in str(e)

    def test_cpu_below_minimum(self):
        manifest = WorkerManifest(
            name="low-cpu",
            worker_class="worker.processor",
            cpu_request=100,
            memory_request=256,
            image="image:v1",
        )
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "100m is below minimum 500m" in str(e)

    def test_memory_below_minimum(self):
        manifest = WorkerManifest(
            name="low-mem",
            worker_class="worker.processor",
            cpu_request=500,
            memory_request=64,
            image="image:v1",
        )
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "64Mi is below minimum" in str(e)

    def test_unknown_worker_class(self):
        manifest = WorkerManifest(
            name="unknown", worker_class="unknown.class",
            cpu_request=500, memory_request=256, image="image:v1",
        )
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "Unknown worker class" in str(e)

    def test_missing_image(self):
        manifest = WorkerManifest(
            name="no-image", worker_class="worker.processor",
            cpu_request=500, memory_request=256, image="",
        )
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "Container image is required" in str(e)

    def test_all_validator_worker_classes(self):
        """Verify every known worker class has documented minimums."""
        for wc in WORKER_CLASS_MINIMUMS:
            min_cpu = WORKER_CLASS_MINIMUMS[wc]["cpu_m"]
            min_mem = WORKER_CLASS_MINIMUMS[wc]["memory_mib"]
            manifest = WorkerManifest(
                name=f"test-{wc.replace('.', '-')}",
                worker_class=wc,
                cpu_request=min_cpu,
                memory_request=min_mem,
                image="test:latest",
            )
            self.validator.validate(manifest)

    def test_negative_replicas(self):
        manifest = WorkerManifest(
            name="neg-replicas", worker_class="worker.processor",
            cpu_request=500, memory_request=256, image="img:v1", replicas=-1,
        )
        try:
            self.validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "Replicas cannot be negative" in str(e)

    def test_validate_dict_convenience(self):
        data = {
            "name": "conv-worker",
            "worker_class": "worker.processor",
            "resources": {"requests": {"cpu": "500m", "memory": "256Mi"}},
            "image": "img:1",
        }
        self.validator.validate_dict(data)

    def test_custom_minimums(self):
        custom = {"worker.processor": {"cpu_m": 1000, "memory_mib": 512}}
        validator = WorkerResourceValidator(custom_minimums=custom)
        manifest = WorkerManifest(
            name="custom-test", worker_class="worker.processor",
            cpu_request=500, memory_request=256, image="img:1",
        )
        try:
            validator.validate(manifest)
            assert False, "Expected ValidationError"
        except ValidationError as e:
            assert "500m is below minimum 1000m" in str(e)
            assert "256Mi is below minimum 512Mi" in str(e)

    def test_at_minimum_passes(self):
        manifest = WorkerManifest(
            name="at-min", worker_class="worker.processor",
            cpu_request=500, memory_request=256, image="img:1",
        )
        self.validator.validate(manifest)
