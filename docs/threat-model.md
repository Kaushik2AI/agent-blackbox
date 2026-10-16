# Threat model

Scope: the dev/portfolio deployment (single developer, shared Linux server or laptop) through v1.
Public multi-tenant hosting is a **non-goal** for v1; anything needed before that is marked.

## Assets

1. Secrets: DB/Redis passwords, future API keys, Hugging Face tokens (M9).
2. Trace contents: prompts, tool arguments/results — may contain customer-like data.
3. Integrity of recorded runs (source executions must be immutable; findings trusted).
4. The host: the user's account and project storage.

## Trust boundaries

| Boundary | Crossing | Control | Status |
|---|---|---|---|
| Other users on a shared server → our ports | TCP to 127.0.0.1 | Services bind 127.0.0.1 only; Postgres SCRAM password; Redis `requirepass`; random 24-byte passwords; per-user ports | ✅ M1 |
| Other users → our files | filesystem | `.env` mode 0600; data dir, socket dir, Redis dir mode 0700; Redis password in 0600 config, not argv | ✅ M1 |
| Browser → API | HTTP via Next.js proxy | Only web port exposed to browser; CORS narrowed to web origin; readiness errors report exception class only (no connection strings) | ✅ M1 (tested) |
| Instrumented agent → ingest API | `POST events:batch` | Schema validation, version rejection (`422`), size limits (`413`, payload truncation), redaction on the client AND again on the server before persistence, idempotency on event/span IDs | ✅ M3 (tested) |
| API → replay worker | Redis job | Only a job id crosses the queue; the intervention is validated against the tool contract before the job exists; the worker re-checks checkpoint integrity; allowlisted tools only | ✅ M6 (tested) |
| Replay worker → outside world | network | `no_network()` patches socket connect/connect_ex/sendto/create_connection for the duration of the replay; an attempt fails the job and is counted as an isolation incident | ✅ M6 (tested) |
| LLM hypothesis text → UI | rendering | Not implemented: no model writes findings; the `kind=hypothesis` slot is reserved and would be rendered as plain text | ⏸ reserved |
| GPU batch output → DB | JSONL import | Schema validation per record, `run_key` dedupe, records with secret-shaped values rejected, traces re-validated by the ingest contract | ✅ M9 (tested) |

## Threats and mitigations (STRIDE-style)

| Threat | Example | Mitigation | Status |
|---|---|---|---|
| Spoofing | Another user on the same server connects to our Postgres on the same node | localhost bind + password auth (no `trust`) | ✅ |
| Tampering | Replay edits the source run | Forks are new rows with a pre-assigned id; source rows are only read; test fingerprints every source row before/after | ✅ M6 |
| Tampering | Corrupted checkpoint restored | SHA-256 verified at ingest and again from disk before every replay; mismatch → ineligible (tested) | ✅ M6 |
| Repudiation | "Which change produced this result?" | `replay_jobs` stores the exact resolved intervention (before/after), checkpoint, sandbox config and mode; fork carries `parent_execution_id` and the same record | ✅ M6 |
| Information disclosure | API key in a tool argument persisted | Metadata-only capture by default; key- and value-pattern redaction on both sides; test with a deliberately non-redacting client | ✅ M3 |
| Information disclosure | Password leaked via error message | Health checks return error class only (tested) | ✅ |
| Information disclosure | `.env` committed | `.gitignore` excludes `.env*` except `.env.example`; example has placeholders only | ✅ |
| Denial of service | Huge ingest batch | Request/payload/batch size limits; rate limits later | ✅ M3 limits · 🚧 M10 rate limits |
| Elevation / side effects | Replay triggers a real email/payment | Only simulated tools exist; network blocked; isolation incidents recorded per job | ✅ M6 |
| Information disclosure | Checkpoint state leaks secrets | States are stored only for content-capture runs and only if a redaction scan finds nothing secret-shaped; otherwise the checkpoint is kept as hash-only | ✅ M6 |

## Known limitations (honest list)

- **No authentication yet.** Since M3/M4 the API stores and serves trace data, so it is
  bound to 127.0.0.1 only and reached by the browser solely through the Next.js server
  (or through an authenticated proxy). Anyone with a shell on the same machine
  could still call the local API port directly. Project-scoped auth is M10; do not expose
  these ports on a network interface before then.
- Anyone who already has your Unix account can read everything; that is out of scope.
- Remote access to the web UI should go through SSH port forwarding or an authenticated
  web-IDE proxy; binding the web server to a public interface is not supported by the scripts.
- Checkpoint states (content-capture runs only) are stored as files under
  `.local-data/artifacts/`; anyone with access to that directory can read them.
- The network guard is in-process. It blocks Python socket APIs, which is what the
  simulated tools could use; it is not an OS-level sandbox (no seccomp/namespace).
