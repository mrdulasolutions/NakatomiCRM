# Nakatomi Roadmap

Nakatomi is a headless, agent-native CRM. This roadmap is organized into phases. Each
item has a status: `[ ]` todo, `[~]` in progress, `[x]` shipped. File references are
clickable paths; bullets that name an adapter/connector have a short design note.

Skip to: [v1 Core](#v1--core-crm-shipped), [v1.1 Repo](#v11--repo-hygiene--agent-surface-in-progress),
[v1.2 Install](#v12--install-surface), [v1.3 Memory](#v13--agentic-memory-interop),
[v1.4 Ingest](#v14--ingest), [v1.5 Dashboard](#v15--local-audit-dashboard),
[v2 Later](#v2--later).

---

## v1 — Core CRM (shipped)

- [x] FastAPI + Postgres + Alembic + Dockerfile + `railway.toml`
- [x] Multi-tenant workspaces; user JWT and per-workspace API keys
- [x] Contacts, Companies, Pipelines/Stages, Deals, Activities, Notes, Tasks
- [x] Relationship graph (typed edges + BFS `/relationships/neighbors`)
- [x] Append-only timeline (`/timeline`)
- [x] HMAC-signed webhooks with retry + delivery log
- [x] Files (pluggable `local` / `s3` backend)
- [x] Soft delete, cursor pagination, bulk upsert, idempotency scaffolding
- [x] Self-describing `/schema` manifest
- [x] MCP server over streamable HTTP at `/mcp` with curated agent tools
- [x] Seed script (`scripts/seed.py`)

## v1.1 — Repo hygiene & agent surface (in progress)

- [x] `ROADMAP.md`
- [x] `LICENSE` (MIT)
- [x] `README.md` — quickstart, deploy, auth, MCP, REST
- [x] `AUTHORS.md`, `CONTRIBUTORS.md`
- [x] `SECURITY.md` — disclosure policy
- [x] `ETHOS.md` — project values
- [x] `CODE_OF_CONDUCT.md`
- [x] `CHANGELOG.md`
- [x] `llms.txt` — LLM-discoverable doc index (served at `/llms.txt`)
- [x] `/.well-known/agent.json` — A2A agent card (served)
- [x] `docs/SKILLS.md` — how agents install Nakatomi as a skill
- [x] `docs/MCP.md` — MCP usage for Claude, Cursor, custom connectors
- [x] Claude Code skill: `nakatomi-crm` — core usage patterns for agents
- [x] Claude Code skill: `nakatomi-dashboard` — "nakatomi dashboard" launch flow
- [ ] OpenAPI hardening — richer `summary`/`examples` per route, tags, problem+json
- [ ] Tests: pytest + httpx against an ephemeral Postgres
- [ ] Ruff + mypy configured in `pyproject.toml`
- [ ] CI: GitHub Actions for lint/test + build/push Docker image

## v1.2 — Install surface

- [x] `docker-compose.yml` — Postgres + app + volume, one `docker compose up`
- [x] `install.sh` — detects Docker or Python; bootstraps a local workspace + key
- [ ] Railway one-click template button in `README.md`
  - Requires publishing to a public GitHub repo, then registering at
    `https://railway.app/new/template` with env var prompts (`SECRET_KEY`,
    `STORAGE_BACKEND`, optional `S3_*`, optional memory connector keys).
- [ ] Fly.io / Render deploy recipes (stretch)
- [ ] Homebrew tap (stretch) — `brew install nakatomi` wrapping the install script
- [ ] PyPI distribution of an `nakatomi` CLI (stretch) — `nakatomi up`, `nakatomi seed`, `nakatomi dashboard`

## v1.3 — Agentic memory interop

**Thesis:** we don't implement semantic memory. Agents already have that. Nakatomi
becomes the **structured source of truth** (people, companies, deals, tasks) and
delegates unstructured recall to external memory systems. Links are bidirectional:
a CRM mutation can write/trigger a memory; a memory write can traceback to a CRM
entity and (optionally) trigger a CRM action.

- [x] `MemoryLink` table — polymorphic: (crm_entity_type, crm_entity_id) ↔ (connector, external_id)
- [x] `MemoryConnector` abstract interface — `store_event`, `recall`, `link`
- [x] Config via env: `MEMORY_CONNECTORS=docdeploy,supermemory` + per-adapter creds
- [x] Adapter stubs:
  - `docdeploy` — x402/MCP memory store, remember/recall API
  - `supermemory` — REST add/search
  - `gbrain` — TODO: point at docs & implement
  - `memcastle` — TODO: point at docs & implement
- [x] `POST /memory/recall` — fan out across configured connectors, merge results
- [x] `POST /memory/link` — explicitly cross-link a CRM entity and an external memory id
- [x] `POST /memory/webhook/{connector}` — inbound: memory system pushed a write → optionally mutate CRM
- [x] Wire `services/events.emit()` to call `store_event` on enabled connectors
- [ ] Per-workspace connector config (currently global via env)
- [ ] Conflict policy surface — what to do when an inbound memory write contradicts a CRM field
- [ ] "Trace" API — `GET /memory/trace/{entity_type}/{entity_id}` returns all known memory refs and their provenance
- [ ] MCP tools: `memory_recall`, `memory_link`, `memory_trace`

## v1.4 — Ingest

**Thesis:** agents will feed Nakatomi from whatever source they're plumbed into
(Apollo, HubSpot, Gmail, PDFs, pasted text). Nakatomi normalizes, dedupes, and lands
clean records. Standardization happens inside Nakatomi so every agent sees the same
shape.

- [x] `POST /ingest` — accepts `{source, format, payload}` and returns diagnostics + created ids
- [x] Adapters scaffold:
  - `csv` — header inference + column map hints
  - `vcard` — parse contacts
  - `json` — generic JSON with a mapping spec
  - `text` — LLM-friendly "note + entity-mention" split (agent does extraction; we standardize)
- [x] Standardization pipeline: lowercase email, E.164 phone, URL canonicalization, whitespace trim, tag dedup
- [ ] Dedup strategies per entity (exact email, domain match, fuzzy name+company)
- [ ] Dry-run mode (`?dry_run=true`) — returns what *would* change
- [ ] Attachment ingest — accept file + mapping spec, produce `File` records + entity links
- [ ] Webhook ingest — accept an inbound webhook from a connector, route to the right adapter

## v1.5 — Local audit dashboard

**Thesis:** the dashboard is a read-only audit surface. It is NOT a product UI. Its
job: let a human confirm at a glance what the agents did last night.

- [x] Minimal FastAPI-served HTML dashboard at `/dashboard` (disabled by default)
- [x] Claude skill: saying "nakatomi dashboard" spins up the stack locally (docker compose) and opens Chrome at `http://localhost:8000/dashboard`
- [ ] Views:
  - [x] Timeline stream (workspace-wide)
  - [x] Recent contacts / companies / deals
  - [ ] Deal pipeline kanban (read-only)
  - [ ] Webhook delivery log
  - [ ] Memory link inspector (per entity)
  - [ ] Audit log search
- [ ] Auth: local-only by default (binds to 127.0.0.1); short-lived session cookie from API key
- [ ] Dark mode + keyboard nav

## v2 — Later

- [ ] Custom fields UI (schema-defined per workspace; fields live in `data` JSONB today)
- [ ] Saved views / queries
- [ ] Durable webhook retry (worker + queue — currently BackgroundTasks)
- [ ] Rate limiting per API key
- [ ] Streaming file upload (currently buffered in memory)
- [ ] pgvector (optional) for workspaces that prefer server-side semantic search
- [ ] Row-level audit diffs (field-level before/after)
- [ ] Merge: "resolve duplicate contacts" flow
- [ ] SSO (Google / GitHub) for human logins
- [ ] OpenTelemetry tracing
- [ ] Export: full workspace dump (JSON + files tarball)
- [ ] Import from legacy CRMs (Salesforce, HubSpot, Pipedrive, Attio) — one-shot migrations

---

## Non-goals (we explicitly won't build these)

- Email sending / email sync — agents already do this (Gmail / Hostinger / Outlook MCP)
- Calendar — agents have Google Calendar MCP
- Marketing automation / drip campaigns — agents compose sequences; we store them as activities
- Forms / landing pages — outside the agent workflow
- Built-in semantic search — delegated to memory connectors
- Rich GUI product — dashboard is audit-only; rich UIs are someone else's product on top of our API
