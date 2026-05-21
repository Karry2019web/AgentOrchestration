# Docker Build Network Policy

## Goal

Ensure the final Docker image stage has **no network access** so that 
image contents never depend on external resources available only at 
build time.

## Multi-Stage Layout

| Stage               | Network | Purpose                              |
|---------------------|---------|--------------------------------------|
| `dependency-resolver` | Allowed | Install Python packages from PyPI    |
| `final`             | **None**  | Copy local artifacts only; no fetches |

## Rules

1. Every `RUN` instruction in the `final` stage **must** carry 
   `--network=none`.
2. The `final` stage must not reference package managers (`pip`, `uv`, 
   `apt`, `apk`, `yum`, `brew`, `cargo`, `npm`, `go install`, etc.).
3. All source code and runtime dependencies are provided via 
   `COPY --from=dependency-resolver`.

## CI Enforcement

The CI workflow builds the `final` target with BuildKit enabled:

```bash
DOCKER_BUILDKIT=1 docker build --target final --check -t agent-orchestrator:ci .
```

The `--check` flag (BuildKit 0.12+) validates the build without executing 
it, which is faster and catches policy violations early.
