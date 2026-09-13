"""User-initiated local-model benchmark reports.

This module deliberately has no background hook.  A report exists only after a
person asks Hermes to run a short local generation, reviews the resulting
closed-shape payload, and explicitly submits it.  Prompts, model output,
paths, host names, account data, aliases, and persistent install identifiers
are never part of the report.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urlparse

from hermes_cli.observability.shared_metrics_send_config import DEFAULT_ENDPOINT


SCHEMA_VERSION = "hermes.local_model_benchmark.v1"
AGENT_PIPELINE_SCHEMA_VERSION = "hermes.local_model_benchmark.agent_pipeline.v1"
_WARMUP_PROMPT = "Reply with exactly the word ready."
_BENCHMARK_PROMPT = (
    "Write the word Hermes exactly 32 times, separated by single spaces."
)
_ENGINE_RE = re.compile(r"^b[0-9]+$")
_FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_QUANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_BACKENDS = frozenset({"cpu", "cuda", "hip", "metal", "unknown", "vulkan"})
_KV_CACHES = frozenset({"f16", "q8_0", "unknown"})
_LOOKUP_PLACEMENTS = frozenset({"disk_backed", "none", "resident", "unknown"})
_SPECULATION = frozenset({"auto", "mtp", "off", "unknown"})
_MAX_BYTES = 1 << 60
_MAX_CONTEXT = 1 << 20
_MAX_SLOTS = 256
_MAX_DURATION_MS = 3_600_000
_MAX_TOKENS = 65_536
_MAX_RATE = 10_000_000


class BenchmarkSubmissionError(RuntimeError):
    """A report cannot be created or sent safely."""


def _nested_mapping(value: Any, key: str) -> Mapping[str, Any]:
    child = value.get(key) if isinstance(value, Mapping) else None
    return child if isinstance(child, Mapping) else {}


def _safe_endpoint(endpoint: str) -> bool:
    """Only HTTPS destinations (or loopback HTTP for tests) may receive a report."""
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    host = parsed.hostname or ""
    if not host or parsed.username or parsed.password:
        return False
    return parsed.scheme == "https" or (
        parsed.scheme == "http" and host in _LOCAL_HOSTS
    )


def submission_enabled(config: Mapping[str, Any] | None) -> bool:
    """Whether this profile has explicitly opted into benchmark submission."""
    telemetry = _nested_mapping(config, "telemetry")
    local = _nested_mapping(telemetry, "local_model_benchmarks")
    return local.get("enabled") is True


def submission_endpoint(config: Mapping[str, Any] | None) -> str:
    """Return the configured ingest endpoint, rejecting an unsafe override."""
    telemetry = _nested_mapping(config, "telemetry")
    local = _nested_mapping(telemetry, "local_model_benchmarks")
    endpoint = local.get("endpoint")
    endpoint = (
        endpoint.strip()
        if isinstance(endpoint, str) and endpoint.strip()
        else DEFAULT_ENDPOINT
    )
    if not _safe_endpoint(endpoint):
        raise BenchmarkSubmissionError(
            "Benchmark submission needs an HTTPS endpoint (localhost HTTP is allowed for testing)."
        )
    return endpoint


def agent_pipeline_instructions(
    *, submission_enabled: bool, preview_lifetime_seconds: int
) -> dict[str, Any]:
    """Return the safe, machine-readable workflow for an assisting agent.

    This is deliberately guidance rather than an authorization mechanism.  A
    previous opt-in does not let an agent submit a new result silently: each
    report still needs to be shown to, and approved by, the person in the
    current conversation.
    """
    return {
        "schema_version": AGENT_PIPELINE_SCHEMA_VERSION,
        "purpose": (
            "Help a person voluntarily run and, only after review, contribute "
            "one local-model benchmark report."
        ),
        "activation": {
            "only_when_user_requests": True,
            "automatic_after_installation": False,
            "automatic_after_activation": False,
            "automatic_after_chat": False,
        },
        "authorization": {
            "guide_is_not_submission_authorization": True,
            "trusted_confirmation_bridge_required": True,
            "model_callable_submit": False,
        },
        "submission": {
            "submission_enabled": bool(submission_enabled),
            "requires_current_user_confirmation": True,
            "confirmation_rule": (
                "Show the exact report to the user, then wait for an explicit "
                "yes before every outbound submission."
            ),
            "preview_lifetime_seconds": preview_lifetime_seconds,
            "one_shot_after_success": True,
        },
        "report_contents": {
            "included": [
                "one-time report ID and timestamp",
                "model family, quant, weights and lookup-table byte counts and placement",
                "selected runtime configuration and generic memory totals",
                "fixed-workload timing, token counts, and token rates",
            ],
            "excluded": [
                "prompts and generated output",
                "model aliases, repositories, and file paths",
                "hostnames, account data, API keys, and persistent install identifiers",
                "device names",
            ],
        },
        "steps": [
            {
                "id": "inspect_local_runtime_readiness",
                "request": {"method": "GET", "path": "/api/local-models/status"},
                "read": ["active_model_id", "server_running"],
                "require": [
                    "server_running is true",
                    "active_model_id is set",
                ],
            },
            {
                "id": "handoff_to_user_controlled_benchmark_flow",
                "action": (
                    "Open or direct the user to the Local Models benchmark card. "
                    "That user-controlled surface runs the local test, renders the "
                    "exact report, and owns the final Submit and confirmation click."
                ),
                "agent_may_call_submission_endpoints": False,
            },
            {
                "id": "revoke_through_the_user_controlled_surface",
                "only_if": "the user asks to stop future benchmark sharing",
                "action": (
                    "Use the Local Models card's Stop sharing control. Do not "
                    "change saved benchmark consent directly from an agent."
                ),
            },
        ],
        "prohibitions": [
            "Never submit automatically or in the background.",
            "Never expose the submit endpoint as a model-callable tool without a trusted user-controlled confirmation bridge.",
            "Never enable submission through the consent endpoint; enable it only as part of a reviewed, confirmed submission.",
            "Never call benchmark, submit, or consent write endpoints directly from a generic agent.",
            "Never alter, supplement, or rebuild the returned report.",
        ],
    }


def _bounded_int(value: Any, *, ceiling: int, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 0 <= value <= ceiling else default


def _bounded_rate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= _MAX_RATE:
        return None
    return round(number, 3)


def _safe_identifier(value: Any, pattern: re.Pattern[str], fallback: str) -> str:
    text = str(value or "").strip()
    return text if pattern.fullmatch(text) else fallback


def _safe_backend(value: Any) -> str:
    backend = str(value or "").strip().lower()
    return backend if backend in _BACKENDS else "unknown"


def _preset_config(
    preset: Mapping[str, Any] | None, *, spilled: bool
) -> dict[str, Any]:
    """Project only Hermes-owned launch fields; never export raw llama.cpp flags."""
    keys = preset if isinstance(preset, Mapping) else {}
    context = _bounded_int(_as_int(keys.get("ctx-size")), ceiling=_MAX_CONTEXT)
    slots = (
        _bounded_int(_as_int(keys.get("parallel")), ceiling=_MAX_SLOTS, default=1) or 1
    )
    kv = str(keys.get("cache-type-k") or "").strip().lower()
    spec_type = str(keys.get("spec-type") or "").strip().lower()
    return {
        "context_tokens": context,
        "slots": slots,
        "kv_cache": kv if kv in _KV_CACHES else "unknown",
        "ordinary_memory_spill": bool(spilled),
        "speculation": spec_type if spec_type in _SPECULATION else "unknown",
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    """Never let a local benchmark request or report silently change host."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):  # noqa: ANN001, D102
        return None


def _open_without_redirect(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_RejectRedirect()).open(request, timeout=timeout)


def managed_local_server_url(server: Mapping[str, Any]) -> str:
    """Return a loopback-only managed-server URL or reject it before any request is built."""
    base_url = server.get("base_url")
    try:
        parsed = urlparse(base_url) if isinstance(base_url, str) else None
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or (parsed.hostname or "") not in _LOCAL_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise BenchmarkSubmissionError("The managed local server is not available.")
    return base_url.rstrip("/")


def prepare_local_model(
    server: Mapping[str, Any], model_id: str, *, timeout: float = 600
) -> None:
    """Explicitly load a staged model through the loopback-only, no-redirect boundary."""
    base_url = managed_local_server_url(server)
    root_url = base_url.rsplit("/v1", 1)[0]
    headers = {"Content-Type": "application/json"}
    api_key = server.get("api_key")
    if isinstance(api_key, str) and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{root_url}/models/load",
        data=json.dumps({"model": model_id}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with _open_without_redirect(request, timeout=timeout):
            pass
    except (OSError, TimeoutError) as exc:
        raise BenchmarkSubmissionError(
            "The managed local server could not load the benchmark model."
        ) from exc


def _request_chat(
    server: Mapping[str, Any], model_id: str, prompt: str
) -> dict[str, Any]:
    base_url = managed_local_server_url(server)
    payload = {
        "max_tokens": 64,
        "messages": [{"content": prompt, "role": "user"}],
        "model": model_id,
        "stream": False,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    api_key = server.get("api_key")
    if isinstance(api_key, str) and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with _open_without_redirect(request, timeout=300) as response:
            decoded = json.loads(response.read())
    except (OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkSubmissionError(
            "The managed local server did not return a usable benchmark response."
        ) from exc
    if not isinstance(decoded, dict):
        raise BenchmarkSubmissionError(
            "The local server returned an invalid benchmark response."
        )
    return decoded


def _response_tokens(response: Mapping[str, Any], key: str) -> int:
    usage = _nested_mapping(response, "usage")
    return _bounded_int(usage.get(key), ceiling=_MAX_TOKENS)


def _response_rate(response: Mapping[str, Any], *keys: str) -> float | None:
    timings = _nested_mapping(response, "timings")
    for key in keys:
        rate = _bounded_rate(timings.get(key))
        if rate is not None:
            return rate
    return None


def run_benchmark(
    *,
    server: Mapping[str, Any],
    model_id: str,
    catalog_id: str | None,
    quant: str | None,
    model_bytes: int,
    lookup_placement: str,
    lookup_table_bytes: int,
    engine_tag: str | None,
    backend: str | None,
    preset: Mapping[str, Any] | None,
    ordinary_memory_spill: bool,
    device_memory_bytes: int,
    system_memory_bytes: int,
    unified_memory: bool,
) -> dict[str, Any]:
    """Warm a staged model, time one fixed local generation, and return its safe report.

    The warm-up makes the reported request a decode/pre-fill measurement rather than a
    download, mmap, or model-load measurement.  Both generated responses are discarded before
    the report is assembled.
    """
    _request_chat(server, model_id, _WARMUP_PROMPT)
    started = time.perf_counter()
    response = _request_chat(server, model_id, _BENCHMARK_PROMPT)
    wall_time_ms = min(
        _MAX_DURATION_MS, max(0, round((time.perf_counter() - started) * 1000))
    )

    family = _safe_identifier(catalog_id, _FAMILY_RE, "sideloaded")
    safe_quant = _safe_identifier(quant, _QUANT_RE, "unknown")
    placement = str(lookup_placement or "").strip().lower()
    safe_placement = placement if placement in _LOOKUP_PLACEMENTS else "unknown"
    tag = str(engine_tag or "").strip()
    runtime = _preset_config(preset, spilled=ordinary_memory_spill)
    return {
        "benchmark": {
            "completion_tokens": _response_tokens(response, "completion_tokens"),
            "completion_tokens_per_second": _response_rate(
                response, "predicted_per_second", "completion_tokens_per_second"
            ),
            "prompt_tokens": _response_tokens(response, "prompt_tokens"),
            "prompt_tokens_per_second": _response_rate(
                response, "prompt_per_second", "prompt_tokens_per_second"
            ),
            "request": "short-generation-v1",
            "wall_time_ms": wall_time_ms,
        },
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "hardware": {
            "device_memory_bytes": _bounded_int(
                device_memory_bytes, ceiling=_MAX_BYTES
            ),
            "system_memory_bytes": _bounded_int(
                system_memory_bytes, ceiling=_MAX_BYTES
            ),
            "unified_memory": bool(unified_memory),
        },
        "model": {
            "family": family,
            "lookup_placement": safe_placement,
            "lookup_table_bytes": _bounded_int(lookup_table_bytes, ceiling=_MAX_BYTES),
            "quant": safe_quant,
            "weights_bytes": _bounded_int(model_bytes, ceiling=_MAX_BYTES),
        },
        "package_id": str(uuid.uuid4()),
        "runtime": {
            "backend": _safe_backend(backend),
            "engine": "llama.cpp",
            "engine_tag": tag if _ENGINE_RE.fullmatch(tag) else "unknown",
            **runtime,
        },
        "schema_version": SCHEMA_VERSION,
    }


def _report_uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise BenchmarkSubmissionError(
            "The benchmark report is missing its package ID."
        )
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid package ID."
        ) from exc
    if parsed.version != 4:
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid package ID."
        )
    return str(parsed)


def _report_time(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise BenchmarkSubmissionError("The benchmark report has an invalid timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid timestamp."
        ) from exc
    if "T" not in value or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BenchmarkSubmissionError("The benchmark report has an invalid timestamp.")
    return value


def _require_mapping(value: Any, name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BenchmarkSubmissionError(
            f"The benchmark report has an invalid {name} section."
        )
    return value


def _require_int(value: Any, name: str, ceiling: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= ceiling
    ):
        raise BenchmarkSubmissionError(f"The benchmark report has an invalid {name}.")
    return value


def _require_rate(value: Any, name: str) -> float | None:
    if value is None:
        return None
    rate = _bounded_rate(value)
    if rate is None:
        raise BenchmarkSubmissionError(f"The benchmark report has an invalid {name}.")
    return rate


def validate_report(value: Any) -> dict[str, Any]:
    """Return a newly-built, closed-shape report or reject arbitrary data before it can leave.

    The desktop receives its preview over HTTP and sends it back on confirmation, so this is the
    last security boundary before a report becomes an outbound request.
    """
    expected = {
        "benchmark",
        "created_at",
        "hardware",
        "model",
        "package_id",
        "runtime",
        "schema_version",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema_version") != SCHEMA_VERSION
    ):
        raise BenchmarkSubmissionError(
            "The benchmark report is not a recognized Hermes report."
        )

    benchmark = _require_mapping(
        value.get("benchmark"),
        "benchmark",
        {
            "completion_tokens",
            "completion_tokens_per_second",
            "prompt_tokens",
            "prompt_tokens_per_second",
            "request",
            "wall_time_ms",
        },
    )
    hardware = _require_mapping(
        value.get("hardware"),
        "hardware",
        {"device_memory_bytes", "system_memory_bytes", "unified_memory"},
    )
    model = _require_mapping(
        value.get("model"),
        "model",
        {"family", "lookup_placement", "lookup_table_bytes", "quant", "weights_bytes"},
    )
    runtime = _require_mapping(
        value.get("runtime"),
        "runtime",
        {
            "backend",
            "context_tokens",
            "engine",
            "engine_tag",
            "kv_cache",
            "ordinary_memory_spill",
            "slots",
            "speculation",
        },
    )

    family = model.get("family")
    quant = model.get("quant")
    placement = model.get("lookup_placement")
    if not isinstance(family, str) or not _FAMILY_RE.fullmatch(family):
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid model family."
        )
    if not isinstance(quant, str) or not _QUANT_RE.fullmatch(quant):
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid model quant."
        )
    if placement not in _LOOKUP_PLACEMENTS:
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid lookup placement."
        )

    engine_tag = runtime.get("engine_tag")
    if runtime.get("engine") != "llama.cpp" or (
        engine_tag != "unknown" and not isinstance(engine_tag, str)
    ):
        raise BenchmarkSubmissionError("The benchmark report has an invalid runtime.")
    if engine_tag != "unknown" and not _ENGINE_RE.fullmatch(engine_tag):
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid runtime build."
        )
    if (
        runtime.get("backend") not in _BACKENDS
        or runtime.get("kv_cache") not in _KV_CACHES
        or runtime.get("speculation") not in _SPECULATION
    ):
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid runtime configuration."
        )
    if not isinstance(runtime.get("ordinary_memory_spill"), bool):
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid memory placement."
        )
    if benchmark.get("request") != "short-generation-v1":
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid benchmark kind."
        )
    if not isinstance(hardware.get("unified_memory"), bool):
        raise BenchmarkSubmissionError(
            "The benchmark report has an invalid hardware section."
        )

    return {
        "benchmark": {
            "completion_tokens": _require_int(
                benchmark.get("completion_tokens"),
                "completion token count",
                _MAX_TOKENS,
            ),
            "completion_tokens_per_second": _require_rate(
                benchmark.get("completion_tokens_per_second"), "completion rate"
            ),
            "prompt_tokens": _require_int(
                benchmark.get("prompt_tokens"), "prompt token count", _MAX_TOKENS
            ),
            "prompt_tokens_per_second": _require_rate(
                benchmark.get("prompt_tokens_per_second"), "prompt rate"
            ),
            "request": "short-generation-v1",
            "wall_time_ms": _require_int(
                benchmark.get("wall_time_ms"), "benchmark duration", _MAX_DURATION_MS
            ),
        },
        "created_at": _report_time(value.get("created_at")),
        "hardware": {
            "device_memory_bytes": _require_int(
                hardware.get("device_memory_bytes"), "device memory", _MAX_BYTES
            ),
            "system_memory_bytes": _require_int(
                hardware.get("system_memory_bytes"), "system memory", _MAX_BYTES
            ),
            "unified_memory": hardware["unified_memory"],
        },
        "model": {
            "family": family,
            "lookup_placement": placement,
            "lookup_table_bytes": _require_int(
                model.get("lookup_table_bytes"), "lookup table bytes", _MAX_BYTES
            ),
            "quant": quant,
            "weights_bytes": _require_int(
                model.get("weights_bytes"), "model weights", _MAX_BYTES
            ),
        },
        "package_id": _report_uuid(value.get("package_id")),
        "runtime": {
            "backend": runtime["backend"],
            "context_tokens": _require_int(
                runtime.get("context_tokens"), "context size", _MAX_CONTEXT
            ),
            "engine": "llama.cpp",
            "engine_tag": engine_tag,
            "kv_cache": runtime["kv_cache"],
            "ordinary_memory_spill": runtime["ordinary_memory_spill"],
            "slots": _require_int(runtime.get("slots"), "slot count", _MAX_SLOTS),
            "speculation": runtime["speculation"],
        },
        "schema_version": SCHEMA_VERSION,
    }


def submit_report(report: Any, *, endpoint: str) -> dict[str, Any]:
    """Send one reviewed report to the configured endpoint and require a success acknowledgement."""
    normalized = validate_report(report)
    if not _safe_endpoint(endpoint):
        raise BenchmarkSubmissionError("Benchmark submission needs an HTTPS endpoint.")
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(normalized, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _open_without_redirect(request, timeout=20) as response:
        # ``getattr`` evaluates its default eagerly, so don't call ``getcode``
        # on a response implementation which exposes only ``status``.
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        if status not in {200, 201, 202}:
            raise BenchmarkSubmissionError(f"Benchmark service returned HTTP {status}.")
    return normalized
