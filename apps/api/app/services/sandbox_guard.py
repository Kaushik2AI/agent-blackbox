"""Network isolation for replays: inside `no_network()`, any attempt to open a socket
connection raises SandboxViolation (and is counted) BEFORE a single byte leaves the
process. Replays only ever run inside this guard."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_lock = threading.Lock()
_PATCHED = (
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
    (socket.socket, "sendto"),
    (socket, "create_connection"),
)


class SandboxViolation(RuntimeError):
    pass


@contextmanager
def no_network(incidents: list[str]) -> Iterator[None]:
    def deny(*args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], socket.socket):
            target = args[1] if len(args) > 1 else None
        else:
            target = args[0] if args else None
        incidents.append(f"blocked outbound connection to {target!r}")
        raise SandboxViolation("network access is forbidden inside a replay sandbox")

    with _lock:
        saved = [(owner, name, getattr(owner, name)) for owner, name in _PATCHED]
        for owner, name, _ in saved:
            setattr(owner, name, deny)
        try:
            yield
        finally:
            for owner, name, original in saved:
                setattr(owner, name, original)
