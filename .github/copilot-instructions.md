# Copilot instructions for NexaCrew (AGENT_AI)

## Versioning — MANDATORY
- The single source of truth is the `VERSION` file at the repository root
  (semantic versioning `MAJOR.MINOR.PATCH`). It drives the auto-updater:
  clients compare their local VERSION against the server's `/api/version`
  and download the update package when the server is newer.
- **EVERY code change in ANY session MUST bump `VERSION` exactly once
  before finishing:**
  - bug fix / small tweak → bump **PATCH** (1.28.0 → 1.28.1)
  - new feature / new setting / new endpoint → bump **MINOR** (1.28.0 → 1.29.0)
  - breaking change (config format, API, database) → bump **MAJOR**
- Never bump more than once per session; never leave the version unchanged
  after editing code. Documentation-only changes do not require a bump.

## Verification workflow (after edits)
- Python: check errors on edited files; run
  `pytest tests --ignore=tests\test_workforce.py -q` from `platform/`
  with `..\.venv\Scripts\python.exe` (expect all passing).
- JS: `node --check platform/static/app.js`.
- Shell scripts: force LF then `bash -n` via WSL.
- Server restart needed for backend changes (uvicorn, port 8600);
  browsers need Ctrl+F5 for frontend changes.

## Engineering standard — enterprise / data-center grade (MANDATORY)
All code must be production-quality. Never produce demo/tutorial-grade code.

### Reliability
- Every external call (network, DB, file, subprocess) gets a timeout,
  retry with exponential backoff + jitter, and a fail-fast path.
- Background threads must have a shutdown event and never touch
  stdin/stdout after console detach (guard REPL loops with a running
  flag and closed-stream checks — see the `ops_console.py`
  `ValueError: I/O operation on closed file` incident).
- Graceful shutdown on SIGTERM/SIGINT: drain in-flight work, close
  connections. Mutating operations must be idempotent when retried.
- No silent failure: bare `except: pass` is forbidden; handle with
  context or propagate.

### Database (SQLite in platform/data/)
- WAL mode + busy_timeout on every connection; deterministic close.
- All multi-step writes inside transactions.
- Back up `platform/data/platform.db` before any migration
  (backups dir already exists). Never bulk-read `platform/data/`.
- Pagination on every list endpoint; no unbounded SELECT *.

### Security
- Validate and sanitize ALL external input. Parameterized queries only.
- Secrets from env vars only — never in code, logs, or comments.
- Every non-public endpoint: auth check + audit-log entry.
- Installers must be idempotent, verify download checksums, and roll
  back on partial failure.

### Observability
- `logging` module with rotating file handlers — never bare `print()`
  in production paths, never unbounded out.log/err.log growth.
- Structured messages with context (what failed, inputs summary,
  remediation hint). Log entry/exit + latency of critical operations.

### Performance
- Stream files >1 MB in request paths — never load whole into memory.
- Bounded worker pools for CPU-bound work; async I/O for network-bound.
- Cache expensive computations with explicit TTL; avoid N+1 queries.

### Chat deliverable expectations
- Include validation, error handling, logging, and tests by default —
  without being asked.
- State failure modes and scaling assumptions when designing.
- Mark unavoidable shortcuts as `TODO(production):`.
- If a request creates production risk (data loss, injection, unbounded
  resource use), say so and propose the safe alternative.
- Consult `docs/chat-history/*.md` for past design decisions before
  redesigning existing features.
