# Ethos

This file is the project's north star. When a decision is ambiguous, we resolve
it by returning to these principles.

## 1. Agents are the primary user

Nakatomi is not a CRM with an agent-friendly API bolted on. It is an agent-native
CRM that happens to expose REST for humans. Every design decision — pagination,
idempotency, self-description, error messages, MCP coverage — assumes the caller
is an LLM-driven agent with imperfect memory and a strong tendency to retry.

## 2. The user owns their data

- The storage backend is yours. Local volume, your S3, your Postgres.
- No phone-home analytics. No telemetry that requires a Nakatomi account.
- A workspace can be exported whole and re-imported into another Nakatomi
  instance. (Export/import is on the roadmap; this is a hard commitment.)

## 3. We are the spine, not the soul

Nakatomi stores structured facts: who, what company, what deal, what stage, what
happened when, who is connected to whom. We delegate *soft* concerns — semantic
recall, email threading, calendar logic, marketing automation — to specialized
systems the user's agent already has plumbed in. We ship connector points; we do
not ship deep integrations we'd be second-best at.

## 4. Composable over opinionated

Every major subsystem has a pluggable interface:

- Storage (`local`, `s3`)
- Memory connectors (`docdeploy`, `supermemory`, …)
- Ingest adapters (`csv`, `vcard`, `json`, `text`)
- Auth (JWT and API key today, OAuth later)

The default adapters should work out of the box; swapping is always an option,
never a rewrite.

## 5. Boring tech, clean lines

- Python + FastAPI + Postgres + Alembic
- Sync SQLAlchemy with a process-level pool
- Explicit migrations
- No magical metaclasses, no plugin frameworks, no DSLs

## 6. Soft delete by default

Agents make mistakes. Humans reviewing what agents did need a way back. Deletes
are soft unless explicitly hard.

## 7. Every mutation is traceable

- Timeline event on write
- Audit log entry on write
- Webhook fire-and-forget to any subscriber
- Actor recorded: which user or which API key made the change

## 8. Never a silent failure

Errors are JSON objects with a human-readable `error` and, when possible, a
`suggestion`. If an agent calls a tool with bad arguments, the error should tell
it exactly what would work instead.

## 9. Keep the agent surface small and stable

Every MCP tool and every REST endpoint is a commitment to agents we can't easily
walk back. We prefer a small set of orthogonal primitives over a sprawling set
of convenience wrappers.

## 10. Non-goals are features

We don't build email sending, calendar, marketing automation, or a rich UI.
Saying no is how we stay useful.
