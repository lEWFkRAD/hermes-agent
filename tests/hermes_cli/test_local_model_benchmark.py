"""Privacy and transport contracts for voluntary local-model benchmark reports.

The benchmark endpoint must be a one-way privacy boundary: a local generation
creates a closed report, the person reviews it, then a short-lived exact copy
may be submitted once.  These tests use only a loopback llama-server stub and
a loopback collector; no report is ever sent to a live service.
"""

from __future__ import annotations

from copy import deepcopy
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hermes_cli.config_defaults import DEFAULT_CONFIG
from hermes_cli.local_runtime import benchmark


class _BenchmarkHandler(BaseHTTPRequestHandler):
    """Loopback llama-server and collector imitation with observable requests."""

    requests: list[tuple[str, dict[str, Any]]] = []
    submissions: list[dict[str, Any]] = []
    redirect_chat = False
    redirect_model_load = False

    def _send(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        type(self).requests.append((self.path, body))
        if self.path == "/v1/chat/completions":
            if type(self).redirect_chat:
                self.send_response(307)
                self.send_header("Location", "/collect")
                self.end_headers()
                return
            self._send(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "model output that must never leave localhost"
                            }
                        }
                    ],
                    "timings": {
                        "predicted_per_second": 47.8912,
                        "prompt_per_second": 123.4567,
                    },
                    "usage": {"completion_tokens": 32, "prompt_tokens": 12},
                },
            )
        elif self.path == "/models/load":
            if type(self).redirect_model_load:
                self.send_response(307)
                self.send_header("Location", "/collect")
                self.end_headers()
                return
            self._send(200, {"ok": True})
        elif self.path == "/collect":
            type(self).submissions.append(body)
            self._send(202, {"accepted": True})
        else:
            self._send(404, {})

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def benchmark_server():
    class Handler(_BenchmarkHandler):
        requests = []
        submissions = []
        redirect_chat = False
        redirect_model_load = False

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    yield base_url, Handler
    server.shutdown()
    server.server_close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_cli import web_server

    test_client = TestClient(web_server.app)
    test_client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return test_client


@pytest.fixture(autouse=True)
def clear_pending_benchmark_reports():
    """The one-shot registry is deliberately process-local, so keep test cases independent."""
    from hermes_cli.web_routers import local_models

    with local_models._PENDING_BENCHMARK_REPORTS_LOCK:
        local_models._PENDING_BENCHMARK_REPORTS.clear()
    yield
    with local_models._PENDING_BENCHMARK_REPORTS_LOCK:
        local_models._PENDING_BENCHMARK_REPORTS.clear()


def _run_report(base_url: str) -> dict[str, Any]:
    return benchmark.run_benchmark(
        server={"api_key": "local-test-key", "base_url": f"{base_url}/v1"},
        model_id="private-local-model-alias",
        catalog_id="qwen3.8-flash-next",
        quant="UD-Q4_K_XL",
        model_bytes=82_523_491_840,
        lookup_placement="disk_backed",
        lookup_table_bytes=28_800_138_240,
        engine_tag="b10679",
        backend="cuda",
        preset={
            "cache-type-k": "q8_0",
            "ctx-size": 131072,
            "parallel": 2,
            "spec-type": "mtp",
        },
        ordinary_memory_spill=False,
        device_memory_bytes=96 << 30,
        system_memory_bytes=128 << 30,
        unified_memory=False,
    )


def _reviewed_report() -> dict[str, Any]:
    """A valid report shaped exactly like a freshly generated local result."""
    return {
        "benchmark": {
            "completion_tokens": 32,
            "completion_tokens_per_second": 47.891,
            "prompt_tokens": 12,
            "prompt_tokens_per_second": 123.457,
            "request": "short-generation-v1",
            "wall_time_ms": 500,
        },
        "created_at": "2026-09-12T12:00:00+00:00",
        "hardware": {
            "device_memory_bytes": 96 << 30,
            "system_memory_bytes": 128 << 30,
            "unified_memory": False,
        },
        "model": {
            "family": "qwen3.8-flash-next",
            "lookup_placement": "disk_backed",
            "lookup_table_bytes": 28_800_138_240,
            "quant": "UD-Q4_K_XL",
            "weights_bytes": 82_523_491_840,
        },
        "package_id": str(uuid.uuid4()),
        "runtime": {
            "backend": "cuda",
            "context_tokens": 131072,
            "engine": "llama.cpp",
            "engine_tag": "b10679",
            "kv_cache": "q8_0",
            "ordinary_memory_spill": False,
            "slots": 2,
            "speculation": "mtp",
        },
        "schema_version": benchmark.SCHEMA_VERSION,
    }


def test_local_run_generates_a_sanitized_report_without_submitting(benchmark_server):
    base_url, handler = benchmark_server

    report = _run_report(base_url)

    assert [path for path, _body in handler.requests] == [
        "/v1/chat/completions",
        "/v1/chat/completions",
    ]
    assert handler.submissions == []
    assert report["benchmark"] == {
        "completion_tokens": 32,
        "completion_tokens_per_second": 47.891,
        "prompt_tokens": 12,
        "prompt_tokens_per_second": 123.457,
        "request": "short-generation-v1",
        "wall_time_ms": report["benchmark"]["wall_time_ms"],
    }
    wire_preview = json.dumps(report)
    for private_value in (
        "private-local-model-alias",
        "model output that must never leave localhost",
        "Reply with exactly the word ready.",
        "Write the word Hermes exactly 32 times, separated by single spaces.",
        "local-test-key",
    ):
        assert private_value not in wire_preview


def test_report_validation_rejects_extra_data_and_naive_timestamps(benchmark_server):
    base_url, _handler = benchmark_server
    report = _run_report(base_url)

    assert benchmark.validate_report(report) == report

    with_path = deepcopy(report)
    with_path["model"]["path"] = "C:/private/models/qwen.gguf"
    with pytest.raises(benchmark.BenchmarkSubmissionError, match="model section"):
        benchmark.validate_report(with_path)

    naive_time = deepcopy(report)
    naive_time["created_at"] = "2026-09-12T12:00:00"
    with pytest.raises(benchmark.BenchmarkSubmissionError, match="timestamp"):
        benchmark.validate_report(naive_time)


def test_submission_config_defaults_to_opt_out_and_rejects_nonlocal_http():
    default = DEFAULT_CONFIG["telemetry"]["local_model_benchmarks"]
    assert default["enabled"] is False
    assert str(default["endpoint"]).startswith("https://")
    assert benchmark.submission_enabled(None) is False
    assert benchmark.submission_enabled({
        "telemetry": {"local_model_benchmarks": {"enabled": True}}
    })
    assert benchmark.submission_endpoint({}).startswith("https://")
    assert (
        benchmark.submission_endpoint({
            "telemetry": {
                "local_model_benchmarks": {"endpoint": "http://127.0.0.1:9988/collect"}
            }
        })
        == "http://127.0.0.1:9988/collect"
    )
    with pytest.raises(benchmark.BenchmarkSubmissionError, match="HTTPS"):
        benchmark.submission_endpoint({
            "telemetry": {
                "local_model_benchmarks": {"endpoint": "http://example.test/collect"}
            }
        })
    with pytest.raises(benchmark.BenchmarkSubmissionError, match="HTTPS"):
        benchmark.submission_endpoint({
            "telemetry": {"local_model_benchmarks": {"endpoint": "https://"}}
        })


def test_benchmark_prompt_cannot_be_routed_to_a_nonlocal_server():
    with pytest.raises(
        benchmark.BenchmarkSubmissionError, match="managed local server"
    ):
        benchmark._request_chat(  # noqa: SLF001 - verify the network boundary directly
            {"base_url": "https://example.test/v1"},
            "private-local-model-alias",
            "fixed benchmark prompt",
        )


def test_local_benchmark_requests_reject_redirects(benchmark_server):
    base_url, handler = benchmark_server
    handler.redirect_chat = True

    with pytest.raises(
        benchmark.BenchmarkSubmissionError, match="usable benchmark response"
    ):
        _run_report(base_url)

    assert [path for path, _body in handler.requests] == ["/v1/chat/completions"]
    assert handler.submissions == []


def test_model_load_cannot_route_to_a_nonlocal_server(monkeypatch):
    called = False

    def unexpected_request(*_args: Any, **_kwargs: Any):
        nonlocal called
        called = True
        raise AssertionError("a nonlocal model-load request must never be opened")

    monkeypatch.setattr(benchmark, "_open_without_redirect", unexpected_request)

    with pytest.raises(
        benchmark.BenchmarkSubmissionError, match="managed local server"
    ):
        benchmark.prepare_local_model(
            {"api_key": "private-local-key", "base_url": "https://example.test/v1"},
            "private-local-model-alias",
        )

    assert called is False


def test_model_load_rejects_a_loopback_redirect(benchmark_server):
    base_url, handler = benchmark_server
    handler.redirect_model_load = True

    with pytest.raises(benchmark.BenchmarkSubmissionError, match="could not load"):
        benchmark.prepare_local_model(
            {"api_key": "private-local-key", "base_url": f"{base_url}/v1"},
            "private-local-model-alias",
        )

    assert [path for path, _body in handler.requests] == ["/models/load"]
    assert handler.submissions == []


def test_explicit_submission_sends_only_the_closed_reviewed_report(benchmark_server):
    base_url, handler = benchmark_server
    report = _run_report(base_url)

    accepted = benchmark.submit_report(report, endpoint=f"{base_url}/collect")

    assert accepted == report
    assert handler.submissions == [report]
    sent = json.dumps(handler.submissions[0])
    assert "private-local-model-alias" not in sent
    assert "model output that must never leave localhost" not in sent


def test_router_requires_opt_in_and_a_current_exact_preview_once(client, monkeypatch):
    from hermes_cli.local_runtime import benchmark as benchmark_module
    from hermes_cli.web_routers import local_models

    generated = _reviewed_report()
    sent: list[dict[str, Any]] = []
    consent_writes: list[bool] = []
    monkeypatch.setattr(local_models, "_benchmark_report", lambda _model_id: generated)
    monkeypatch.setattr(local_models, "_load_config", lambda: {})
    monkeypatch.setattr(
        local_models, "_set_benchmark_submission_enabled", consent_writes.append
    )

    def submit(report: dict[str, Any], *, endpoint: str) -> dict[str, Any]:
        sent.append(report)
        return report

    monkeypatch.setattr(benchmark_module, "submit_report", submit)

    preview = client.post(
        "/api/local-models/benchmark", json={"model_id": "private-local-model-alias"}
    )
    assert preview.status_code == 200
    report = preview.json()["report"]
    assert sent == []

    no_consent = client.post(
        "/api/local-models/benchmark/submit", json={"report": report}
    )
    assert no_consent.status_code == 403
    assert sent == []

    fabricated = deepcopy(report)
    fabricated["model"]["weights_bytes"] += 1
    rejected = client.post(
        "/api/local-models/benchmark/submit",
        json={
            "enable_submission": True,
            "report": fabricated,
        },
    )
    assert rejected.status_code == 422
    assert sent == []

    submitted = client.post(
        "/api/local-models/benchmark/submit",
        json={
            "enable_submission": True,
            "report": report,
        },
    )
    assert submitted.status_code == 200
    assert sent == [report]
    assert consent_writes == [True]

    replayed = client.post(
        "/api/local-models/benchmark/submit",
        json={
            "enable_submission": True,
            "report": report,
        },
    )
    assert replayed.status_code == 422
    assert sent == [report]


def test_revoking_consent_discards_unsubmitted_previews(client, monkeypatch):
    from hermes_cli.local_runtime import benchmark as benchmark_module
    from hermes_cli.web_routers import local_models

    consent_writes: list[bool] = []
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        local_models, "_benchmark_report", lambda _model_id: _reviewed_report()
    )
    monkeypatch.setattr(local_models, "_load_config", lambda: {})
    monkeypatch.setattr(
        local_models, "_set_benchmark_submission_enabled", consent_writes.append
    )
    monkeypatch.setattr(
        benchmark_module,
        "submit_report",
        lambda report, *, endpoint: sent.append(report) or report,
    )

    preview = client.post(
        "/api/local-models/benchmark", json={"model_id": "private-local-model-alias"}
    )
    assert preview.status_code == 200
    report = preview.json()["report"]

    revoked = client.post(
        "/api/local-models/benchmark/consent", json={"enabled": False}
    )
    assert revoked.status_code == 200
    assert consent_writes == [False]

    stale = client.post(
        "/api/local-models/benchmark/submit",
        json={"enable_submission": True, "report": report},
    )
    assert stale.status_code == 422
    assert sent == []


def test_failed_submission_keeps_consent_off_and_releases_the_preview(
    client, monkeypatch
):
    from hermes_cli.local_runtime import benchmark as benchmark_module
    from hermes_cli.web_routers import local_models

    generated = _reviewed_report()
    consent_writes: list[bool] = []
    monkeypatch.setattr(local_models, "_benchmark_report", lambda _model_id: generated)
    monkeypatch.setattr(local_models, "_load_config", lambda: {})
    monkeypatch.setattr(
        local_models, "_set_benchmark_submission_enabled", consent_writes.append
    )

    preview = client.post(
        "/api/local-models/benchmark", json={"model_id": "private-local-model-alias"}
    )
    report = preview.json()["report"]

    def fail_submit(_report: dict[str, Any], *, endpoint: str) -> dict[str, Any]:
        raise benchmark_module.BenchmarkSubmissionError("collector unavailable")

    monkeypatch.setattr(benchmark_module, "submit_report", fail_submit)
    failed = client.post(
        "/api/local-models/benchmark/submit",
        json={
            "enable_submission": True,
            "report": report,
        },
    )
    assert failed.status_code == 422
    assert consent_writes == []

    monkeypatch.setattr(
        benchmark_module, "submit_report", lambda submitted, *, endpoint: submitted
    )
    retried = client.post(
        "/api/local-models/benchmark/submit",
        json={
            "enable_submission": True,
            "report": report,
        },
    )
    assert retried.status_code == 200
    assert consent_writes == [True]
