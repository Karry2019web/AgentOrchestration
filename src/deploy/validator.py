"""Worker manifest resource validator — validates CPU/memory requests against workload-class minimums."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Per-worker-class minimum resource requirements
# CPU in millicores (m), memory in MiB
WORKER_CLASS_MINIMUMS: Dict[str, Dict[str, int]] = {
    "worker.processor": {
        "cpu_m": 500,       # 0.5 CPU cores
        "memory_mib": 256,  # 256 MiB
    },
    "worker.analyzer": {
        "cpu_m": 1000,      # 1.0 CPU cores
        "memory_mib": 512,  # 512 MiB
    },
    "worker.extractor": {
        "cpu_m": 500,       # 0.5 CPU cores
        "memory_mib": 384,  # 384 MiB
    },
    "worker.sink": {
        "cpu_m": 250,       # 0.25 CPU cores
        "memory_mib": 128,  # 128 MiB
    },
    "monitor.watcher": {
        "cpu_m": 250,
        "memory_mib": 128,
    },
}


class ValidationError(Exception):
    """Raised when a worker manifest fails resource validation."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__("; ".join(errors))


def _parse_cpu(value: str) -> int:
    """Parse a CPU resource string to millicores.

    Accepts formats: '500m' (500 millicores), '1' (1 core = 1000m),
    '0.5' (0.5 cores = 500m).
    """
    if value.endswith("m"):
        return int(value.rstrip("m"))
    if "." in value:
        return int(float(value) * 1000)
    return int(value) * 1000


def _parse_memory(value: str) -> int:
    """Parse a memory resource string to MiB.

    Accepts: '256Mi', '512M', '1Gi' (1024 MiB), '268435456' (bytes).
    """
    value = value.strip()
    if value.endswith("Gi"):
        return int(float(value.rstrip("Gi")) * 1024)
    if value.endswith("Mi"):
        return int(value.rstrip("Mi"))
    if value.endswith("M"):
        return int(value.rstrip("M"))
    if value.endswith("Ki"):
        return int(value.rstrip("Ki")) // 1024
    if value.endswith("k"):
        return int(value.rstrip("k")) // 1024
    # Assume bytes
    try:
        return int(value) // (1024 * 1024)
    except ValueError:
        raise ValidationError([f"Cannot parse memory value: {value}"])


@dataclass
class WorkerManifest:
    """A parsed worker deployment manifest."""

    name: str
    worker_class: str
    cpu_request: Optional[int] = None  # millicores
    memory_request: Optional[int] = None  # MiB
    cpu_limit: Optional[int] = None  # millicores
    memory_limit: Optional[int] = None  # MiB
    replicas: int = 1
    image: str = ""
    env: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerManifest":
        """Parse a manifest dictionary into a WorkerManifest."""
        name = data.get("name", "")
        worker_class = data.get("worker_class", data.get("type", ""))

        resources = data.get("resources", {})
        requests = resources.get("requests", {})
        limits = resources.get("limits", {})

        cpu_request = _parse_cpu(requests["cpu"]) if "cpu" in requests else None
        memory_request = _parse_memory(requests["memory"]) if "memory" in requests else None
        cpu_limit = _parse_cpu(limits["cpu"]) if "cpu" in limits else None
        memory_limit = _parse_memory(limits["memory"]) if "memory" in limits else None

        return cls(
            name=name,
            worker_class=worker_class,
            cpu_request=cpu_request,
            memory_request=memory_request,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            replicas=data.get("replicas", 1),
            image=data.get("image", ""),
            env=data.get("env", {}),
        )


class WorkerResourceValidator:
    """Validates worker manifests against workload-class resource minimums."""

    def __init__(self, custom_minimums: Optional[Dict[str, Dict[str, int]]] = None):
        self._minima = dict(WORKER_CLASS_MINIMUMS)
        if custom_minimums:
            for cls_name, reqs in custom_minimums.items():
                if cls_name in self._minima:
                    self._minima[cls_name].update(reqs)
                else:
                    self._minima[cls_name] = reqs

    def validate(self, manifest: WorkerManifest) -> None:
        """Validate a manifest, raising ValidationError on failure."""
        errors: List[str] = []

        # 1. Name is required
        if not manifest.name:
            errors.append("Worker name is required")

        # 2. Worker class is required
        if not manifest.worker_class:
            errors.append("Worker class is required")
        elif manifest.worker_class not in self._minima:
            classes = ", ".join(sorted(self._minima.keys()))
            errors.append(
                f"Unknown worker class '{manifest.worker_class}'. "
                f"Known classes: {classes}"
            )
        else:
            # 3. Validate CPU request
            min_cpu = self._minima[manifest.worker_class]["cpu_m"]
            if manifest.cpu_request is None:
                errors.append(
                    f"CPU request is missing. "
                    f"Minimum for '{manifest.worker_class}' is {min_cpu}m "
                    f"({min_cpu / 1000:.1f} cores)"
                )
            elif manifest.cpu_request < min_cpu:
                errors.append(
                    f"CPU request {manifest.cpu_request}m is below minimum "
                    f"{min_cpu}m for '{manifest.worker_class}' "
                    f"(requested {manifest.cpu_request / 1000:.2f} cores, "
                    f"minimum {min_cpu / 1000:.1f} cores)"
                )

            # 4. Validate memory request
            min_mem = self._minima[manifest.worker_class]["memory_mib"]
            if manifest.memory_request is None:
                errors.append(
                    f"Memory request is missing. "
                    f"Minimum for '{manifest.worker_class}' is {min_mem}MiB"
                )
            elif manifest.memory_request < min_mem:
                errors.append(
                    f"Memory request {manifest.memory_request}Mi is below minimum "
                    f"{min_mem}Mi for '{manifest.worker_class}'"
                )

        # 5. Image is required for deployment
        if not manifest.image:
            errors.append("Container image is required")

        # 6. Replicas must be non-negative
        if manifest.replicas < 0:
            errors.append(f"Replicas cannot be negative (got {manifest.replicas})")

        if errors:
            raise ValidationError(errors)

    def validate_dict(self, data: dict) -> None:
        """Convenience: parse dict and validate in one call."""
        manifest = WorkerManifest.from_dict(data)
        self.validate(manifest)
