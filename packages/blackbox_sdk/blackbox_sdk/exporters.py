"""Exporters: where finished batches go.

HttpExporter retries transport errors, 429 and 5xx with backoff. That is safe because the
ingest API is idempotent (events dedupe on event_id, spans on span_id). 4xx other than 429
are not retried: they mean the batch itself is wrong.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


class ExportError(RuntimeError):
    pass


class MemoryExporter:
    def __init__(self) -> None:
        self.batches: list[dict[str, Any]] = []

    def export(self, batch: dict[str, Any]) -> dict[str, Any]:
        self.batches.append(json.loads(json.dumps(batch)))
        return {"stored": "memory"}


class JsonlExporter:
    """Append batches to a JSONL file (offline runs, e.g. SCC batch jobs in M9)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def export(self, batch: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(batch, sort_keys=True) + "\n")
        return {"stored": str(self.path)}


class HttpExporter:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        retries: int = 4,
        backoff_s: float = 0.25,
        timeout_s: float = 10.0,
        token: str | None = None,
    ) -> None:
        self.url = base_url.rstrip("/") + "/api/v1/events:batch"
        # Public deployments only accept batches carrying the ingest token.
        self.headers = {"x-ingest-token": token} if token else {}
        self.client = client or httpx.Client(timeout=timeout_s)
        self.retries = retries
        self.backoff_s = backoff_s

    def export(self, batch: dict[str, Any]) -> dict[str, Any]:
        last: str = ""
        for attempt in range(self.retries + 1):
            try:
                resp = self.client.post(self.url, json=batch, headers=self.headers)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    result: dict[str, Any] = resp.json()
                    return result
                if resp.status_code != 429 and resp.status_code < 500:
                    raise ExportError(f"ingest rejected batch: HTTP {resp.status_code} {resp.text}")
                last = f"HTTP {resp.status_code}"
            if attempt < self.retries:
                time.sleep(self.backoff_s * (2**attempt))
        raise ExportError(f"ingest unavailable after {self.retries + 1} attempts ({last})")
