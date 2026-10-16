# blackbox_sdk — record agent runs (M3)

```python
from blackbox_sdk.exporters import HttpExporter
from blackbox_sdk.integrations.agent_harness import run_traced

run, responses = run_traced("invalid_inventory_argument", HttpExporter("http://127.0.0.1:8000"))
```

or from the shell: `make seed-demo` (= `python -m blackbox_sdk.seed_demo --capture-content`).

| Piece | What it does |
|---|---|
| `recorder.py` | Spans (32-hex trace id, 16-hex span ids, parent links, epoch-ms times, GenAI semantic-convention attribute names) and events (monotonic `sequence_no`, UUID `event_id`), batched per contract v1.0. |
| `redaction.py` | Client-side redaction, identical to the server's (a test enforces it). |
| `exporters.py` | `HttpExporter` (retries transport errors/429/5xx with backoff; safe because ingest is idempotent), `JsonlExporter` (offline, e.g. GPU batch jobs), `MemoryExporter` (tests). |
| `integrations/agent_harness.py` | Hooks the demo agent's event stream: one `invoke_agent` root span, a `chat` span per model decision, an `execute_tool` span per tool call, plus fixture and final-sandbox-state artifact references (SHA-256 only). |

**Capture policy.** Default is metadata only: payloads keep field names and value shapes
(`{"product_name": "<str len=12>"}`), not values. `capture_content=True` keeps values after
redaction; the demo fixtures are synthetic, which is why `make seed-demo` turns it on.

**Honest scope.** The data model is OpenTelemetry-compatible but the wire format is this
project's JSON contract; an OTLP exporter is not implemented.
