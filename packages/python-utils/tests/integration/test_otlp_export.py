"""All three signals reach a real collector, and no planted secret goes with them.

Run with: pytest tests/integration -m integration -v -s

Each case emits from a FRESH subprocess. OTel's global tracer/meter/logger providers
can only be set once per process -- a second `init()` is ignored with a warning -- so
emitting twice in one interpreter would silently send the second batch through the
first (already shut down) provider and drop it. That would make these tests pass or
fail purely on collection order.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable

import pytest

pytestmark = pytest.mark.integration

# Endpoints and the OTLP-JSON counter arrive via fixtures rather than an import:
# tests/integration is not a package, so a relative import cannot resolve.
Counter = Callable[[pathlib.Path], dict[str, int]]

# Planted probes. Each corresponds to a guarantee the sanitizer actually makes:
#   email        -> free-text PII (the EMAIL_REGEX rule)
#   api_key=     -> a structured sensitive field (is_sensitive_key)
#   ?token=      -> a sensitive key/value inside a URL, which is where the ASGI
#                   instrumentor puts request URLs and therefore where a token leaks
# A bare random token in prose is deliberately NOT probed: redact_text guarantees
# emails and sensitive key/value pairs, not arbitrary high-entropy strings.
PLANTED_EMAIL = "planted.secret@example.com"
PLANTED_KEY_VALUE = "sk-KEYPLANTED"
PLANTED_URL_TOKEN = "sk-URLPLANTED"

# Present in the same log line, and asserted to ARRIVE. Without it a broken exporter
# that ships nothing at all would pass the "no secret present" assertions trivially.
MARKER = "marker_ok_export_happened"

_EMITTER = textwrap.dedent(
    f"""
    import time
    import penguintechinc_utils as u

    tel = u.init(service_name="itest")
    u.get_logger("itest").info(
        "{MARKER} user {PLANTED_EMAIL} hit "
        "https://api.example.com/v1?token={PLANTED_URL_TOKEN}",
        api_key="{PLANTED_KEY_VALUE}",
    )
    with u.timed("itest.work"):
        time.sleep(0.01)
    tel.shutdown()
    """
)


def _emit_from_subprocess(endpoint: str, protocol: str) -> None:
    """Emit a log record, a span and a histogram from a clean interpreter."""
    env = {
        **os.environ,
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_PROTOCOL": protocol,
        # The 60s default exports no metrics at all inside a test window.
        "OTEL_METRIC_EXPORT_INTERVAL": "500",
    }
    env.pop("OTEL_SDK_DISABLED", None)
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _EMITTER],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"emitter failed:\n{proc.stdout}\n{proc.stderr}"


def _settle() -> None:
    """Wait out the SDK batch processors plus the collector's 1s file flush."""
    time.sleep(4)


def test_all_signals_reach_the_collector(
    otlp_collector: dict[str, object],
    signal_counts: Counter,
) -> None:
    """Logs, metrics (incl. a histogram) and spans must all arrive, with counts printed."""
    _emit_from_subprocess(str(otlp_collector["http_endpoint"]), "http/protobuf")
    _settle()

    counts = signal_counts(pathlib.Path(str(otlp_collector["output"])))
    print(
        f"logRecords={counts['logs']} metrics={counts['metrics']} "
        f"histograms={counts['histograms']} spans={counts['spans']}"
    )

    assert counts["logs"] >= 1, "no log records were exported"
    assert counts["metrics"] >= 1, "no metrics were exported"
    assert counts["histograms"] >= 1, "no histogram metrics were exported"
    assert counts["spans"] >= 1, "no spans were exported"


def test_no_planted_secret_is_exported(
    otlp_collector: dict[str, object],
    signal_counts: Counter,
) -> None:
    """Zero occurrences of each planted secret, and the marker present to prove export.

    The marker assertion is the non-zero denominator: without it, an exporter that
    shipped nothing would satisfy every "not in" assertion below.
    """
    _emit_from_subprocess(str(otlp_collector["http_endpoint"]), "http/protobuf")
    _settle()

    output = pathlib.Path(str(otlp_collector["output"]))
    blob = output.read_text() if output.exists() else ""
    counts = signal_counts(output)
    print(
        f"exported bytes={len(blob)} logRecords={counts['logs']} "
        f"metrics={counts['metrics']} spans={counts['spans']}"
    )

    assert MARKER in blob, "export never happened, so the redaction proof is vacuous"
    assert blob.count(PLANTED_EMAIL) == 0, "planted email reached the collector"
    assert blob.count(PLANTED_KEY_VALUE) == 0, "planted api_key value reached the collector"
    assert blob.count(PLANTED_URL_TOKEN) == 0, "planted URL token reached the collector"
    assert "[REDACTED]" in blob or "[email]" in blob, "nothing was redacted at all"


def test_grpc_protocol_also_exports(
    otlp_collector: dict[str, object],
    signal_counts: Counter,
) -> None:
    """The default grpc protocol must work too, not just http/protobuf.

    Both exporters ship in this library, so shipping one that was never exercised
    against a real collector would be untested by construction.
    """
    _emit_from_subprocess(str(otlp_collector["grpc_endpoint"]), "grpc")
    _settle()

    counts = signal_counts(pathlib.Path(str(otlp_collector["output"])))
    print(f"grpc: logRecords={counts['logs']} metrics={counts['metrics']} spans={counts['spans']}")
    assert counts["logs"] >= 1, "no log records exported over grpc"
    assert counts["spans"] >= 1, "no spans exported over grpc"
    assert counts["metrics"] >= 1, "no metrics exported over grpc"
