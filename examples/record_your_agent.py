"""Record a run of YOUR agent with the FlightPath SDK and open it in the app.

    python examples/record_your_agent.py http://127.0.0.1:8000

Replace the two hand-written steps with calls from your own agent loop: one span per
model decision and per tool call, one event when each finishes.
"""

from __future__ import annotations

import sys
import uuid

from blackbox_sdk.exporters import HttpExporter
from blackbox_sdk.recorder import Recorder, Resource

api = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
rec = Recorder(
    resource=Resource(
        project="my-team",
        agent="refund-bot",
        git_sha="abc1234",  # your agent's code version
        config_hash="prompt-v3",  # anything that identifies its configuration
        model_name="qwen2.5-7b-instruct",
    ),
    execution_id=str(uuid.uuid4()),
    task_id="refund-ticket-42",
    capture_content=True,  # default False: keep field names and value shapes only
)
root = rec.start_span("invoke_agent refund-bot", "agent")

# 1. The model decides to call a tool (its reasoning is optional).
llm = rec.start_span("chat qwen2.5-7b-instruct", "llm", parent=root)
rec.add_event(
    llm,
    "llm_call_end",
    status="ok",
    operation="chat",
    attributes={"gen_ai.usage.input_tokens": 812, "gen_ai.usage.output_tokens": 41},
    payload={"action": "tool_call", "tool": "lookup_order", "note": "Find the order first."},
)
rec.end_span(llm)

# 2. The tool call fails.
tool = rec.start_span("execute_tool lookup_order", "tool", parent=root)
rec.add_event(
    tool,
    "tool_call_end",
    status="error",
    operation="execute_tool",
    tool_name="lookup_order",
    attributes={"error_type": "not_found", "call_index": 0},
    payload={
        "input_redacted": rec.capture({"order_id": "a-1001"}),
        "error_code": "ORDER_NOT_FOUND",
        "error_message": "no order a-1001",
    },
)
rec.end_span(tool, "error")

rec.end_span(root, "error")
rec.finish("failed", {"termination": "tool_failure"})
exporter = HttpExporter(api)
for batch in rec.to_batches():
    print(exporter.export(batch))
print(f"open /runs/{rec.execution_id} in the app")
