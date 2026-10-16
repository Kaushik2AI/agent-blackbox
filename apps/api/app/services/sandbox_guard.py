"""Network isolation for replays: inside `no_network()`, any attempt to open a socket
connection raises SandboxViolation (and is counted) BEFORE a single byte leaves the
process. Replays only ever run inside this guard.

`allow` names the only destinations that stay reachable: a replay of a real-model run
must still call the model API (and nothing else). Scripted replays allow nothing.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_lock = threading.Lock()
_tls = threading.local()
_PATCHED = (
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
    (socket.socket, "sendto"),
    (socket, "create_connection"),
)


class SandboxViolation(RuntimeError):
    pass


def _resolve(allow: list[tuple[str, int]]) -> set[tuple[str, int]]:
    allowed: set[tuple[str, int]] = set()
    for host, port in allow:
        allowed.add((host, port))
        try:
            for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
                allowed.add((str(info[4][0]), port))
        except OSError:
            pass
    return allowed


@contextmanager
def no_network(incidents: list[str], allow: list[tuple[str, int]] | None = None) -> Iterator[None]:
    allowed = _resolve(allow or [])

    with _lock:
        saved = {(owner, name): getattr(owner, name) for owner, name in _PATCHED}

        def guard(owner: Any, name: str) -> Any:
            original = saved[(owner, name)]

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if args and isinstance(args[0], socket.socket):
                    target = args[1] if len(args) > 1 else None
                else:
                    target = args[0] if args else None
                ok = (
                    isinstance(target, tuple)
                    and len(target) >= 2
                    and (str(target[0]), int(target[1])) in allowed
                )
                if ok and name == "create_connection":
                    # The allowed host may resolve to a different address than it did
                    # when the guard started (DNS round-robin): trust the connect() that
                    # create_connection makes for this allowed host name.
                    _tls.trusted = True
                    try:
                        return original(*args, **kwargs)
                    finally:
                        _tls.trusted = False
                if ok or (name == "connect" and getattr(_tls, "trusted", False)):
                    return original(*args, **kwargs)
                incidents.append(f"blocked outbound connection to {target!r}")
                raise SandboxViolation("network access is forbidden inside a replay sandbox")

            return wrapper

        for owner, name in _PATCHED:
            setattr(owner, name, guard(owner, name))
        try:
            yield
        finally:
            for (owner, name), original in saved.items():
                setattr(owner, name, original)
