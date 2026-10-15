# Threat model

Scope: the dev/portfolio deployment (single developer, BU SCC or laptop) through v1.
Public multi-tenant hosting is a **non-goal** for v1; anything needed before that is marked.

## Assets

1. Secrets: DB/Redis passwords, future API keys, Hugging Face tokens (M9).
2. Trace contents: prompts, tool arguments/results — may contain customer-like data.
3. Integrity of recorded runs (source executions must be immutable; findings trusted).
4. The host: SCC account and project storage.

## Trust boundaries

| Boundary | Crossing | Control | Status |
|---|---|---|---|
| Other users on a shared SCC compute node → our ports | TCP to 127.0.0.1 | Services bind 127.0.0.1 only; Postgres SCRAM password; Redis `requirepass`; random 24-byte passwords; per-user ports | ✅ M1 |
| Other users → our files | filesystem | `.env` mode 0600; data dir, socket dir, Redis dir mode 0700; Redis password in 0600 config, not argv | ✅ M1 |
| Browser → API | HTTP via Next.js proxy | Only web port exposed to browser; CORS narrowed to web origin; readiness errors report exception class only (no connection strings) | ✅ M1 (tested) |
| Instrumented agent → ingest API | `POST events:batch` | Schema validation, version rejection (`422`), size limits (`413`, payload truncation), redaction on the client AND again on the server before persistence, idempotency on event/span IDs | ✅ M3 (tested) |
| API → replay worker | Redis job | Job args validated before enqueue; worker re-validates; allowlisted tools only | 🚧 M6 |
| Replay worker → outside world | network | No network in sandbox; socket-level block asserted in tests | 🚧 M6 |
| LLM hypothesis text → UI | rendering | Rendered as plain text, labelled *Hypothesis*, never executed | 🚧 M5 |
| SCC batch output → DB | JSONL import | Schema validation, dedupe by run ID, reject secrets/tokens | 🚧 M9 |

## Threats and mitigations (STRIDE-style)

| Threat | Example | Mitigation | Status |
|---|---|---|---|
| Spoofing | Another SCC user connects to our Postgres on the same node | localhost bind + password auth (no `trust`) | ✅ |
| Tampering | Replay edits the source run | Forks are new rows; source is never updated; test asserts byte-equality of source domain records | 🚧 M6 |
| Tampering | Corrupted checkpoint restored | SHA-256 `state_hash` verified before restore; mismatch → ineligible | 🚧 M6 |
| Repudiation | "Which change produced this result?" | Intervention record + lineage + environment fingerprint stored per fork | 🚧 M6 |
| Information disclosure | API key in a tool argument persisted | Metadata-only capture by default; key- and value-pattern redaction on both sides; test with a deliberately non-redacting client | ✅ M3 |
| Information disclosure | Password leaked via error message | Health checks return error class only (tested) | ✅ |
| Information disclosure | `.env` committed | `.gitignore` excludes `.env*` except `.env.example`; example has placeholders only | ✅ |
| Denial of service | Huge ingest batch | Request/payload/batch size limits; rate limits later | ✅ M3 limits · 🚧 M10 rate limits |
| Elevation / side effects | Replay triggers a real email/payment | Only simulated tools exist; network blocked; isolation-incident counter must be 0 | 🚧 M6 |
| Elevation | LLM analysis contains code that gets run | Never executed; displayed as text | 🚧 M5 |

## Known limitations (honest list)

- **No authentication yet.** Since M3/M4 the API stores and serves trace data, so it is
  bound to 127.0.0.1 only and reached by the browser solely through the Next.js server
  (on SCC, behind BU's authenticated OnDemand proxy). Anyone with a shell on the same node
  could still call the local API port directly. Project-scoped auth is M10; do not expose
  these ports on a network interface before then.
- Anyone who already has your Unix account can read everything; that is out of scope.
- SCC OnDemand access to the web UI goes through BU's authenticated OnDemand session;
  binding the web server to a non-localhost interface is not supported by the scripts.
