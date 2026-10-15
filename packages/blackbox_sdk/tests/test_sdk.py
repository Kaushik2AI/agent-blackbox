"""SDK unit tests: span tree, IDs, ordering, content policy, redaction, exporters."""

import json
import re
from pathlib import Path

import httpx
import pytest

from blackbox_sdk.exporters import ExportError, HttpExporter, JsonlExporter, MemoryExporter
from blackbox_sdk.integrations.agent_harness import run_traced
from blackbox_sdk.recorder import Recorder, Resource

RES = Resource(project="t", agent="a", git_sha="g", config_hash="c", model_name="m")


def traced(fixture: str, **kw: bool) -> dict:
    mem = MemoryExporter()
    run_traced(fixture, mem, **kw)
    assert len(mem.batches) == 1
    return mem.batches[0]


def test_otel_compatible_ids_and_single_trace() -> None:
    b = traced("exchange_success")
    trace_ids = {s["trace_id"] for s in b["spans"]} | {e["trace_id"] for e in b["events"]}
    assert len(trace_ids) == 1 and re.fullmatch(r"[0-9a-f]{32}", trace_ids.pop())
    assert all(re.fullmatch(r"[0-9a-f]{16}", s["span_id"]) for s in b["spans"])
    assert len({s["span_id"] for s in b["spans"]}) == len(b["spans"])


def test_span_tree_root_llm_and_tool_spans() -> None:
    b = traced("invalid_inventory_argument")
    roots = [s for s in b["spans"] if s["parent_span_id"] is None]
    assert len(roots) == 1 and roots[0]["kind"] == "agent"
    children = [s for s in b["spans"] if s["parent_span_id"] == roots[0]["span_id"]]
    assert len(children) == len(b["spans"]) - 1
    tools = [s for s in children if s["kind"] == "tool"]
    assert [s["attributes"]["gen_ai.tool.name"] for s in tools] == (
        ["lookup_order"] + ["lookup_inventory"] * 7
    )
    assert [s["status"] for s in tools] == ["ok"] + ["error"] * 7
    assert all(s["end_ms"] is not None and s["end_ms"] >= s["start_ms"] for s in b["spans"])


def test_events_ordered_and_attached_to_known_spans() -> None:
    b = traced("transient_inventory_timeout")
    seq = [e["sequence_no"] for e in b["events"]]
    assert seq == list(range(len(seq)))
    span_ids = {s["span_id"] for s in b["spans"]}
    assert all(e["span_id"] in span_ids for e in b["events"])
    assert b["events"][0]["event_type"] == "agent_start"
    assert b["events"][-1]["event_type"] == "agent_end"


def test_failing_tool_event_carries_error_code_and_type() -> None:
    b = traced("invalid_inventory_argument")
    err = next(
        e for e in b["events"] if e["event_type"] == "tool_call_end" and e["status"] == "error"
    )
    assert err["tool_name"] == "lookup_inventory"
    assert err["payload"]["error_code"] == "SKU_REQUIRED"
    assert err["attributes"]["error_type"] == "validation_error"


def test_metadata_only_by_default_keeps_shape_not_values() -> None:
    b = traced("invalid_inventory_argument")
    text = json.dumps(b["events"])
    assert "red backpack" not in text and "ORD-1001" not in text
    err = next(e for e in b["events"] if e["status"] == "error" and e["tool_name"])
    assert err["payload"]["input_redacted"] == {"product_name": "<str len=12>"}
    assert err["payload"]["capture"] == "metadata_only"


def test_capture_content_is_opt_in() -> None:
    b = traced("invalid_inventory_argument", capture_content=True)
    err = next(e for e in b["events"] if e["status"] == "error" and e["tool_name"])
    assert err["payload"]["input_redacted"] == {"product_name": "red backpack"}
    assert err["payload"]["capture"] == "content"


def test_execution_summary_and_provenance_artifacts() -> None:
    b = traced("exchange_success")
    ex = b["execution"]
    assert ex["status"] == "succeeded" and ex["ended_at"]
    assert ex["attributes"]["verifier"]["passed"] is True
    assert ex["attributes"]["fixture"]["id"] == "exchange_success"
    uris = {a["uri"] for a in b["artifacts"]}
    assert "fixture://exchange_success@1.0.0" in uris
    assert any(u.startswith("sandbox-state://") for u in uris)


def test_secrets_are_redacted_even_with_content_capture() -> None:
    rec = Recorder(
        resource=RES,
        execution_id="00000000-0000-4000-8000-000000000001",
        task_id="t",
        capture_content=True,
    )
    span = rec.start_span("s", "tool", attributes={"api_key": "abc123"})
    rec.add_event(
        span,
        "tool_call_end",
        payload={
            "headers": {"Authorization": "Bearer abcdefghijklmnop"},
            "note": "key sk-ABCDEFGHIJKLMNOPQRST and mail jane@example.com",
            "password": "hunter2",
        },
    )
    text = json.dumps(rec.to_batches())
    for secret in [
        "abc123",
        "abcdefghijklmnop",
        "sk-ABCDEFGHIJKLMNOPQRST",
        "jane@example.com",
        "hunter2",
    ]:
        assert secret not in text
    assert rec.redactions >= 5


def test_batches_chunk_events_and_keep_spans_in_first() -> None:
    rec = Recorder(resource=RES, execution_id="00000000-0000-4000-8000-000000000002", task_id="t")
    span = rec.start_span("s", "agent")
    for _ in range(25):
        rec.add_event(span, "tick")
    batches = rec.to_batches(max_events=10)
    assert [len(b["events"]) for b in batches] == [10, 10, 5]
    assert [len(b["spans"]) for b in batches] == [1, 0, 0]


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_http_exporter_retries_server_errors_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    exp = HttpExporter("http://api", client=_client(handler), backoff_s=0)
    assert exp.export({"x": 1}) == {"ok": 1}
    assert len(calls) == 3 and calls[0].url.path == "/api/v1/events:batch"


def test_http_exporter_does_not_retry_client_errors() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(422, json={"detail": "bad"})

    with pytest.raises(ExportError, match="422"):
        HttpExporter("http://api", client=_client(handler), backoff_s=0).export({})
    assert len(calls) == 1


def test_http_exporter_gives_up_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ExportError, match="unavailable"):
        HttpExporter("http://api", client=_client(handler), retries=2, backoff_s=0).export({})


def test_jsonl_exporter(tmp_path: Path) -> None:
    exp = JsonlExporter(tmp_path / "out" / "runs.jsonl")
    run_traced("exchange_success", exp)
    run_traced("refund_out_of_stock", exp)
    lines = (tmp_path / "out" / "runs.jsonl").read_text().splitlines()
    assert [json.loads(line)["execution"]["task_id"] for line in lines] == [
        "exchange_success",
        "refund_out_of_stock",
    ]


def test_client_and_server_redaction_rules_are_identical() -> None:
    repo = Path(__file__).resolve().parents[3]
    server = (repo / "apps/api/app/redaction.py").read_text()
    client = (repo / "packages/blackbox_sdk/blackbox_sdk/redaction.py").read_text()

    def body(src: str) -> str:
        return src.split('"""', 2)[2]  # drop the module docstring

    assert body(server) == body(client)
