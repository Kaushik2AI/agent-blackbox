"""Per-execution sandbox: an isolated copy of the fixture world plus a side-effect store.

Each run gets its own Sandbox built from a deep copy of the fixture, so two executions
(or, from M6, a source run and its fork) can never see each other's writes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Effect:
    kind: str  # "draft" | "resolution"
    effect_id: str
    payload: dict[str, Any]


@dataclass
class Sandbox:
    world: dict[str, Any]
    faults: dict[str, int] = field(default_factory=dict)  # tool name -> remaining failures
    effects: list[Effect] = field(default_factory=list)

    @classmethod
    def from_fixture(cls, world: dict[str, Any], faults: dict[str, int]) -> Sandbox:
        return cls(world=copy.deepcopy(world), faults=dict(faults))

    def consume_fault(self, tool: str) -> bool:
        """True if an injected fault fires for this call (and uses it up)."""
        remaining = self.faults.get(tool, 0)
        if remaining > 0:
            self.faults[tool] = remaining - 1
            return True
        return False

    def record_effect(self, kind: str, payload: dict[str, Any]) -> str:
        # Deterministic IDs so repeated runs of a fixture produce identical state.
        effect_id = f"{kind}-{sum(1 for e in self.effects if e.kind == kind) + 1}"
        self.effects.append(Effect(kind=kind, effect_id=effect_id, payload=dict(payload)))
        return effect_id

    def effects_of(self, kind: str) -> list[dict[str, Any]]:
        return [e.payload for e in self.effects if e.kind == kind]

    # ------------------------------------------------------------- checkpoints (M6)
    def snapshot(self) -> dict[str, Any]:
        """JSON-serialisable copy of everything needed to resume from this point."""
        return copy.deepcopy(
            {
                "world": self.world,
                "faults": self.faults,
                "effects": [
                    {"kind": e.kind, "effect_id": e.effect_id, "payload": e.payload}
                    for e in self.effects
                ],
            }
        )

    @classmethod
    def restore(cls, snapshot: dict[str, Any]) -> Sandbox:
        """A NEW, independent sandbox: writes to it never reach the snapshot's source."""
        snap = copy.deepcopy(snapshot)
        return cls(
            world=snap["world"],
            faults=dict(snap["faults"]),
            effects=[Effect(e["kind"], e["effect_id"], e["payload"]) for e in snap["effects"]],
        )
