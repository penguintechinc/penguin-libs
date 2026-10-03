"""Fixture running a real OTLP collector for the integration suite.

Asserting against a live collector is the only way to know the exporters are wired
correctly: every in-process test would still pass if nothing ever left the process,
which is exactly the failure mode this library exists to prevent (elder's log bridge
attached no handler and silently exported zero records for months).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator

import pytest

# Pinned by digest, not by tag: an external image must be immutable per the
# dependency-pinning rule. Tag shown for humans; the digest is what is pulled.
COLLECTOR_IMAGE = (
    "otel/opentelemetry-collector-contrib@sha256:"
    "213886eb6407af91b87fa47551c3632be1a6419ff3a5114ef1e6fc364628496f"
)
COLLECTOR_TAG = "otel/opentelemetry-collector-contrib:0.144.0"

# Non-default host ports, so the fixture cannot collide with a collector a developer
# already has running locally.
HTTP_PORT = 14318
GRPC_PORT = 14317

_CONFIG = pathlib.Path(__file__).parent / "collector-config.yaml"


def _docker() -> str:
    """Return the docker executable path.

    Missing docker is a SKIP locally (a developer may not have it) but a hard FAILURE
    under CI, where docker is always present: a gate that silently skips itself in CI
    is the same defect as masking it with `|| true`, and this is the only test that
    proves anything actually leaves the process.
    """
    found = shutil.which("docker")
    if found is None:
        if os.environ.get("CI"):
            pytest.fail("docker is missing in CI; the OTLP integration gate cannot be skipped")
        pytest.skip("docker is required for the OTLP integration tests")
    return found


@pytest.fixture
def signal_counts() -> Callable[[pathlib.Path], dict[str, int]]:
    """Expose the OTLP-JSON counter as a fixture.

    A fixture rather than an import: tests/integration is not a package, so a
    relative import from conftest cannot resolve.
    """
    return read_signal_counts


@pytest.fixture
def otlp_collector(tmp_path: pathlib.Path) -> Iterator[dict[str, object]]:
    """Run a collector writing every received signal to a temp JSON-lines file.

    Yields {"output": <path>}. A failure to start is a hard error, never a skip: a
    silently skipped sink is the same defect as masking a gate with `|| true`.
    """
    docker = _docker()
    outdir = tmp_path / "collector-out"
    outdir.mkdir()
    outdir.chmod(0o777)  # the collector runs as a different uid inside the container
    name = f"penguin-utils-otlp-{int(time.time() * 1000)}"

    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            docker,
            "run",
            "--rm",
            "--detach",
            "--name",
            name,
            "--publish",
            f"{HTTP_PORT}:4318",
            "--publish",
            f"{GRPC_PORT}:4317",
            "--volume",
            f"{_CONFIG}:/etc/otelcol-contrib/config.yaml:ro",
            "--volume",
            f"{outdir}:/output",
            COLLECTOR_IMAGE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"could not start the OTLP collector ({COLLECTOR_TAG}): {proc.stderr.strip()}")

    try:
        _wait_until_running(docker, name)
        yield {
            "output": outdir / "telemetry.json",
            "http_endpoint": f"http://localhost:{HTTP_PORT}",
            "grpc_endpoint": f"http://localhost:{GRPC_PORT}",
        }
    finally:
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [docker, "rm", "--force", name], capture_output=True, check=False
        )


def _wait_until_running(docker: str, name: str, timeout: float = 30.0) -> None:
    """Block until the container reports running, failing loudly if it never does."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [docker, "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            check=False,
        )
        if state.stdout.strip() == "true":
            time.sleep(1.0)  # give the OTLP listeners a moment to bind
            return
        time.sleep(0.5)
    logs = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [docker, "logs", name], capture_output=True, text=True, check=False
    )
    pytest.fail(f"collector never reached running state; logs:\n{logs.stdout}\n{logs.stderr}")


def read_signal_counts(path: pathlib.Path) -> dict[str, int]:
    """Count log records, metrics, histograms and spans in the collector's output.

    The OTLP-JSON top-level keys are `resourceLogs`, `resourceMetrics` and
    `resourceSpans`. `resourceTraces` does not exist -- reading that name would
    count zero spans forever while the assertion still passed on the other signals,
    which is a gate that cannot fail.
    """
    counts = {"logs": 0, "metrics": 0, "histograms": 0, "spans": 0}
    if not path.exists():
        return counts
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        for resource in payload.get("resourceLogs", []):
            for scope in resource.get("scopeLogs", []):
                counts["logs"] += len(scope.get("logRecords", []))
        for resource in payload.get("resourceMetrics", []):
            for scope in resource.get("scopeMetrics", []):
                for metric in scope.get("metrics", []):
                    counts["metrics"] += 1
                    if "histogram" in metric or "exponentialHistogram" in metric:
                        counts["histograms"] += 1
        for resource in payload.get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                counts["spans"] += len(scope.get("spans", []))
    return counts
