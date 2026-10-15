"""Client-side redaction (the server applies the same rules again; never trust one side).

Rules (kept identical to apps/api/app/redaction.py, enforced by a test):
  * values under sensitive-looking keys are replaced entirely;
  * secret-shaped strings (API keys, bearer tokens, JWTs, cloud keys) are replaced anywhere;
  * e-mail addresses are masked (demo traces must not hold customer PII).
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Matched against the key split into lowercase words (camelCase and -/./_ separated), so
# "apiKey", "X-Api-Key" and "client_secret" match but "passed" or "total_tokens" do not.
SENSITIVE_KEY = re.compile(
    r"(^|_)(pass|password|passwd|pwd|secret|token|api_?key|authori[sz]ation|cookie|"
    r"session_?id|credentials?|private_?key|access_?key)(_|$)"
)


def _normalise_key(key: str) -> str:
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return re.sub(r"[^a-z0-9]+", "_", key.lower())


SECRET_VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)),
    ("api_key", re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("hf_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]


class Redactor:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, value: Any, key: str | None = None) -> Any:
        if key is not None and SENSITIVE_KEY.search(_normalise_key(key)):
            self.count += 1
            return REDACTED
        if isinstance(value, dict):
            return {k: self(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        if isinstance(value, str):
            return self._scrub(value)
        return value

    def _scrub(self, text: str) -> str:
        for label, pattern in SECRET_VALUE_PATTERNS:
            text, n = pattern.subn(f"[REDACTED:{label}]", text)
            self.count += n
        return text
