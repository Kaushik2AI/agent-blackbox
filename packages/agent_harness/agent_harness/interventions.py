"""Controlled interventions applied during replay (M6).

Exactly one intervention per fork. Each one targets a single tool call by its call index
and is validated against the tool's contract BEFORE the replay runs:

* ReplaceToolArguments - the call executes with these arguments instead (must pass the
  tool's input schema, so a "fix" can never smuggle in fields the tool does not accept);
* ReplaceToolResult    - the call is not executed; this result is returned instead (must
  match the tool's output schema).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agent_harness.tools import TOOLS


class InterventionError(ValueError):
    pass


@dataclass(frozen=True)
class ReplaceToolArguments:
    call_index: int
    arguments: dict[str, Any]
    type: str = "replace_tool_argument"


@dataclass(frozen=True)
class ReplaceToolResult:
    call_index: int
    result: dict[str, Any]
    type: str = "replace_tool_result"


Intervention = ReplaceToolArguments | ReplaceToolResult


def validate_intervention(intervention: Intervention, tool: str) -> Intervention:
    """Raise InterventionError unless the intervention is valid for `tool`."""
    spec = TOOLS.get(tool)
    if spec is None:
        raise InterventionError(f"{tool!r} is not an allowlisted tool")
    try:
        if isinstance(intervention, ReplaceToolArguments):
            spec.input_model.model_validate(intervention.arguments)
        else:
            spec.output_model.model_validate(intervention.result)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        kind = "arguments" if isinstance(intervention, ReplaceToolArguments) else "result"
        raise InterventionError(f"{kind} do not match the {tool} contract: {problems}") from None
    return intervention
