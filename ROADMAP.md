# Nakatomi Roadmap

> **See also:** [AgentLab.md](./AgentLab.md) — recipes for real-world agent
> deployments. This file is *what we build*; AgentLab is *how you'd use it*.
>
> **Ethos:** [ETHOS.md](./ETHOS.md) — agents are the primary user; spine not
> soul; small stable tool surface; user owns data.
>
> **Lane:** Agent spine (self-hostable structured truth for multi-agent GTM),
> not an Attio/HubSpot clone and not a rich product UI.

This roadmap is ranked by a **P-system** (P0 → P4). Within each priority,
items are ordered by impact. Status: `[ ]` todo · `[~]` in progress · `[x]` shipped.

---

## Protocol stack (north star)

Nakatomi speaks four complementary agent protocols. Together they make the CRM
operable by tools, by peer agents, and by long-running multi-agent workflows.

```text
┌─────────────────────────────────────────────────────────────────────┐
│  Agents (Claude, Cursor, ChatGPT, custom swarms, REVA, OpenGateway) │
└─────────────┬───────────────────┬───────────────────┬───────────────┘
              │                   │                   │
     ┌────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
     │  MCP            │ │  A2A            │ │  ACP            │
     │  Model Context  │ │  Agent2Agent    │ │  Agent Context  │
     │  Protocol       │ │  (Google / LF)  │ │  + Communication│
     │  tools + data   │ │  peer agents    │ │  session context│
     └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  Nakatomi core            │
                    │  REST · Postgres · Events │
                    │  Auth · Timeline · Graph  │
                    └───────────────────────────┘
```

| Layer | Standard | Role in Nakatomi | Status today |
| --- | --- | --- | --- |
| **MCP** | Anthropic Model Context Protocol | Agents call CRM *tools* (`create_contact`, `forecast`, …) over streamable HTTP at `/mcp` | Shipped (curated tools + OAuth 2.1) |
| **A2A** | Google Agent2Agent (Linux Foundation) | Peer agents *discover* Nakatomi, *delegate tasks*, stream status, return *artifacts* | Partial — static `/.well-known/agent.json` only |
| **ACP** | Agent Context Protocol (Nakatomi product layer) + Agent Communication Protocol (BeeAI/IBM → converging into A2A) | **Context:** ship a machine-readable session pack (schema, views, policies, open work). **Communication:** long-running multi-agent handoffs where A2A tasks map onto CRM tasks/timeline | Not started as a product surface |
| **REST** | OpenAPI 3 | Humans, scripts, non-MCP clients; always parity target with MCP | Shipped |

### Why all four (not “just MCP”)

- **MCP** answers: *“What can I do to this CRM right now?”* (tool calls).
- **A2A** answers: *“Which agent should own this work, and how do we track it across agents?”* (discovery, tasks, messages, artifacts).
- **ACP (context)** answers: *“What does an agent need loaded before it starts so it doesn’t invent schema every turn?”* (workspace context packs).
- **ACP (communication heritage)** and **A2A** are converging under the Linux Foundation; Nakatomi tracks the unified A2A surface while shipping **Agent Context** as our differentiated CRM layer.

### Design rules for protocol work

1. Every capability remains available over **REST** (no protocol-only features).
2. MCP tools stay **few, orthogonal, compound where useful** — not one tool per REST route.
3. A2A **Tasks** map to first-class CRM work (tasks, approval requests, jobs) with timeline events — never a parallel shadow system.
4. ACP context packs are **versioned, scoped by API key capabilities, and cacheable**.
5. Errors stay agent-readable (`error` + `suggestion`); never silent failure ([ETHOS.md](./ETHOS.md)).

---

## Priority index

| Priority | Theme | Outcome |
| --- | --- | --- |
| [**P0**](#p0--trust-safety-and-ship-readiness) | Trust, safety, ship-readiness | You can give an agent a key without fear |
| [**P1**](#p1--agent-protocol-stack-mcp--a2a--acp) | Protocol stack (MCP + A2A + ACP) | Discoverable, delegable, context-loaded |
| [**P2**](#p2--crm-spine-completeness) | CRM spine completeness | Real B2B funnels without inventing objects |
| [**P3**](#p3--agent-operations--ergonomics) | Agent ops & ergonomics | Swarms, hygiene, forensics, bulk work |
| [**P4**](#p4--ecosystem-adoption--later) | Ecosystem, adoption, later | Importers, verticals, optional depth |

**Suggested sequencing:** P0 → P1 core A2A/ACP → P2 leads/views → P3 compounds → P4 importers.

**90-day slice (recommended):**

| Month | Focus | Ship |
| --- | --- | --- |
| **1** | P0 + P1 foundations | CI/migrations, scoped keys, idempotency audit, A2A card v1.0 compliance, ACP context pack v0 |
| **2** | P2 spine | Leads+convert, deal roles, saved views, company merge |
| **3** | P1 tasks + P3 ops | A2A task runtime, HITL approvals, compound MCP tools, dead-letter API, HubSpot import MVP |

---

## Shipped foundation (do not regress)

Historical v1–v0.3 surface. Treat as **done** unless a P-item reopens it.

### Core CRM

- [x] FastAPI + Postgres + Alembic + Dockerfile + `railway.toml`
- [x] Multi-tenant workspaces; user JWT and per-workspace API keys
- [x] Contacts, companies, pipelines/stages, deals, activities, notes, tasks
- [x] Products + deal line items (price snapshot) + forecast endpoint
- [x] Relationship graph (typed edges + BFS neighbors)
- [x] Append-only timeline + row-level audit diffs on PATCH
- [x] HMAC webhooks with durable worker (`SKIP LOCKED`, backoff, delivery log)
- [x] Files (local / S3), streaming upload/download
- [x] Soft delete, cursor pagination, bulk upsert, idempotency scaffolding
- [x] Custom field definitions (values in `data` JSONB)
- [x] Contact fuzzy duplicates + merge
- [x] Export / import JSON workspace dump
- [x] Welcome / bootstrap first-run flow
- [x] Thin email (IMAP/SMTP) + calendar (iCal) adapters
- [x] Memory connector framework (DocDeploy, Supermemory, GBrain) + links
- [x] Ingest (CSV, vCard, JSON, text) + standardization pipeline
- [x] Local audit dashboard (opt-in)
- [x] OAuth 2.1 + PKCE for MCP clients
- [x] Rate limiting per API key
- [x] Self-describing `/schema`, `/llms.txt`, static A2A card
- [x] Claude skills: `nakatomi-crm`, `nakatomi-dashboard`
- [x] ~109 pytest tests (not yet CI-gated)

### Explicit non-goals (still features)

We will **not** build:

- Full marketing automation / drip / forms / landing pages
- Rich GUI product (dashboard stays audit-only)
- Built-in semantic search as the primary memory (delegate to connectors)
- Deep email client / sequence executor (agents compose sequences; we store structured state)
- Zapier-style visual workflow builder (prefer declarative policies + webhooks)

**Ethos clarification (P0 item):** email/calendar shipped as *thin I/O adapters* for activity logging. They are not a retreat into Superhuman/HubSpot Sales. Document this in ETHOS so the contradiction dies.

---

## P0 — Trust, safety, and ship-readiness

> **Goal:** production keys, clean deploys, agent-safe writes. Nothing else scales without this.

### P0.1 — CI and migration hardness

- [x] GitHub Actions: `ruff` + `mypy` + `pytest` against ephemeral Postgres
- [x] CI step: `alembic upgrade head` on a clean database (catches ordering bugs) — `tests/test_migrations.py` + `TEST_MIGRATE_URL`
- [x] CI step: clean venv install of `requirements.txt` (catch mcp/pydantic pin fights)
- [x] Migration `0001` left as `create_all` **by design** (documented debt; later revs are explicit; CI covers chain)
- [x] Comment top-level deps in `requirements.txt` with pin reasons
- [x] Publish test count + badge in README

**Why:** Railway first-deploy lessons ([docs/DEPLOYMENT_LESSONS.md](./docs/DEPLOYMENT_LESSONS.md)) must become guardrails, not folklore.

### P0.2 — Capability-scoped API keys

- [x] Scope model on `ApiKey`: e.g. `contacts:read|write`, `deals:write`, `email:send`, `delete:none`, `export:read`, `admin:keys`
- [x] Default new keys: write without hard-delete; no email send until granted
- [x] Enforce scopes on **all** REST resource routers (`enforce_resource_scope`) + MCP tools
- [x] REST: scopes on key create response (shown once with the plaintext key)
- [x] Document in `llms.txt`, README, and MCP tool scope checks

**Why:** Giving Claude a full-admin key is the #1 reason operators won’t run agentic CRM in production.

### P0.3 — Idempotency end-to-end

- [x] Global `IdempotencyMiddleware` for all mutating REST with API keys
- [x] MCP: `idempotency_key` on core mutators (`create_contact/company/deal/task/product`, `add_line_item`, …)
- [x] Replay returns original status + body + header `Idempotent-Replay: true`
- [x] Tests for double-create contact + key reuse conflict

**Why:** Agents retry. Silent duplicates destroy trust faster than missing features.

### P0.4 — Human-in-the-loop (HITL) approvals

- [x] `ApprovalRequest` entity: `action`, `payload`, `status` (pending/approved/rejected/expired/executed), actors, `expires_at`, optional entity refs
- [x] Workspace policies: `workspace.data.policies.approvals` (e.g. force HITL on `email.send`)
- [x] REST: `POST /approvals`, `GET /approvals`, `POST /approvals/{id}/decide`
- [x] MCP: `propose_action`, `list_pending_approvals`, `decide_approval` (owner/admin or `admin:keys`)
- [x] Timeline events: `approval.requested`, `approval.decided`, `approval.executed`
- [ ] A2A: approval decisions can complete or fail an A2A Task (**→ P1**)

**Why:** Salesforce headless guidance and enterprise buyers both require pause-and-approve for money-moving actions.

### P0.5 — Ethos + email/calendar decision (document, don’t thrash)

- [x] Update [ETHOS.md](./ETHOS.md): thin I/O adapters are in-scope; sequence engines and marketing are not
- [x] README “What we are / aren’t” section aligned with shipped adapters
- [x] Gate `send_email` behind `email:send` scope (+ optional approval policy)

### P0.6 — Observability baseline

- [x] `X-Request-Id` on every response (accept inbound or generate)
- [x] Structured access logs: `method path status ms request_id actor` (API key prefix, never secrets)
- [x] OpenTelemetry hooks — optional export (**v1.0**, `docs/OBSERVABILITY.md`)
- [x] `/health/deep` — DB ping (503 if down)

### P0 status: **DONE**

---

## P1 — Agent protocol stack (MCP + A2A + ACP)

> **Goal:** Nakatomi is a first-class citizen of the 2026 agent internet — tools (MCP), peers (A2A), and session context (ACP).

### P1.1 — MCP maturity (keep surface small)

**Shipped:** streamable HTTP `/mcp`, OAuth, curated tools including products/forecast/email/calendar/memory/ingest.

- [x] **Parity matrix** — [docs/MCP_PARITY.md](./docs/MCP_PARITY.md)
- [x] Compound tools:
  - [x] `upsert_account_map`
  - [x] `advance_deal`
  - [x] `log_interaction`
  - [x] `morning_briefing`
  - [x] `load_context` (ACP)
- [x] Tool descriptions include scope requirements (via `_require_scopes` errors + docs)
- [ ] MCP resource templates (optional): `crm://contact/{id}`, `crm://deal/{id}`
- [ ] Version MCP tool schemas; deprecate with `sunset` notes in `/schema`

**Non-goal:** one MCP tool per REST endpoint.

### P1.2 — A2A (Agent2Agent) full surface

#### P1.2.a — Agent Card compliance

- [x] Align card with A2A-shaped fields + skills + securitySchemes
- [x] Serve both `/.well-known/agent.json` and `/.well-known/agent-card.json` (dynamic)
- [x] **Dynamic** card injects real base URL from request
- [x] Skills map to compound capabilities
- [x] Authenticated extended card (`nakatomi.extended` + tool hints)
- [x] Tests: `tests/test_p1_protocols.py`

#### P1.2.b — A2A Task runtime

| A2A | Nakatomi |
| --- | --- |
| Task | `a2a_tasks` + optional CRM `Task` / `ApprovalRequest` |
| Message | `messages` JSONB |
| Artifact | `artifacts` JSONB |

- [x] REST binding at `/a2a/tasks` (documented in [docs/A2A.md](./docs/A2A.md))
- [x] Lifecycle: submitted/working/input_required/completed/failed/canceled
- [x] `input-required` + `require_approval` → HITL approvals; decide resumes/fails task
- [ ] Artifacts as Files (JSON artifacts shipped; File link later)
- [x] Auth scopes `a2a:invoke` (member default includes it)
- [x] Events `a2a.task.created` / `a2a.task.updated` (webhook-capable)

#### P1.2.c — A2A as multi-agent CRM fabric

- [x] Patterns documented in [docs/A2A.md](./docs/A2A.md)
- [ ] Optional: Nakatomi as A2A *client* to remote agents

### P1.3 — ACP — Agent Context Protocol (product differentiator)

- [x] `GET /acp/context` — full pack
- [x] `GET /acp/context?sections=…` — partial
- [x] ETag / `If-None-Match` → 304
- [x] MCP `load_context`
- [x] A2A tasks include `context_url` + optional `context_etag`
- [ ] Optional signed context tokens
- [x] Docs: [docs/ACP.md](./docs/ACP.md)
- [x] Tests: pack shape + ETag 304

#### ACP session conventions

- [x] Documented boot: `load_context` → work → `morning_briefing`
- [x] Scopes enforced (403 + suggestion)

### P1.4 — Discovery cluster (keep coherent)

- [x] `/schema` entity + endpoint manifest
- [x] `/llms.txt`
- [x] `/.well-known/agent.json` + `agent-card.json` (dynamic)
- [x] `/acp/context` (ACP)
- [x] `GET /discovery` index
- [x] Version bump in CHANGELOG (`0.5.0`)

### P1 status: **DONE** (stretch: MCP resources, File artifacts, A2A client outcalls)

---

## P2 — CRM spine completeness

> **Goal:** agents can run a real B2B funnel without inventing objects in `data` JSONB.

### P2.1 — Leads + conversion

- [x] `Lead` entity: name, email, phone, company_name, source, status, score, owner, tags, data
- [x] Lifecycle statuses: `new → working → qualified → unqualified → converted`
- [x] `POST /leads/{id}/convert` → Contact + optional Company + optional Deal in one transaction
- [x] Timeline: `lead.converted` with id mapping
- [x] MCP: `create_lead`, `search_leads`, `convert_lead`
- [x] Duplicate detection against contacts by email before convert (`GET /leads/{id}/duplicates`)

### P2.2 — Deal participants & account hierarchy

- [x] `DealParticipant` roles: `champion`, `economic_buyer`, `legal`, `user`, `influencer`, `other`
- [x] `Company.parent_company_id`
- [x] REST participants on `/deals/{id}/participants`; primary contact sync
- [x] Graph neighbors still work for free-form edges

### P2.3 — Saved views / segments

- [x] `SavedView`: name, slug, entity_type, filter DSL, sort, owner, is_default
- [x] Filter operators: eq, ne, in, gt/gte/lt/lte, contains, is_null, is_not_null, tag_any, relative `P7D`/`-P14D`
- [x] REST: list/create + `POST /views/{slug|id}/run`
- [x] MCP: `list_views`, `run_view`
- [x] Seed defaults: open_deals, tasks_due_this_week, new_leads, pending_approvals, stale_deals

### P2.4 — Quotes (versioned, headless)

- [x] `Quote` linked to deal: version, status, currency, totals
- [x] `QuoteLineItem` snapshots
- [x] Optional `file_id` for PDF (agent attaches File)
- [x] Accept quote → optional deal amount sync + timeline
- [x] MCP: `create_quote`, `set_quote_status`

### P2.5 — Contact / company hygiene

- [x] `ContactChannel` rows (email/phone/linkedin/other)
- [x] Company merge (`POST /companies/merge`)
- [ ] Ingest dry-run (`?dry_run=true`) — carry-forward
- [ ] Attachment ingest + webhook ingest adapters

### P2.6 — Custom fields v2

- [ ] Runtime validation against field definitions (type, required, enum)
- [ ] MCP/schema expose validation errors with suggestions
- [ ] (Stretch → P4) Custom **objects**

### P2.7 — Forecast quality

- [ ] Commit categories
- [ ] Multi-currency FX
- [ ] Trend vs prior period

### P2 status: **CORE DONE** (v0.6.0) — stretch: custom field validation, forecast polish, ingest dry-run

---

## P3 — Agent operations & ergonomics

> **Goal:** multi-agent production ops — forensics, bulk, policy, recovery.

### P3.1 — Declarative policies (not a workflow builder)

- [x] Policy documents in `workspace.data.policies`:
  - approvals (existing), required_fields, auto_tasks, block
- [x] Evaluate on deal PATCH + lead create → 422 + suggestion
- [x] MCP: `list_policies`
- [ ] Rate / burst limits per key class (partially via existing API key rate limits)

### P3.2 — Async jobs & bulk

- [x] `Job` entity: ingest | export | merge | custom | a2a_batch
- [x] `POST /jobs` + `GET /jobs/{id}` + cancel pending
- [x] In-process async runner (thread)
- [x] MCP: `start_job`, `get_job`
- [ ] Auto-promote large ingest to jobs (threshold)

### P3.3 — Event catalog & dead letters

- [x] Event types already in `/schema` + ACP pack
- [x] `GET /webhooks/dead-letters` + `POST .../replay`
- [ ] Full AgentLab recovery recipe (doc later)

### P3.4 — Time-travel & audit search

- [x] `GET /entities/{type}/{id}/as-of?ts=`
- [x] `GET /audit` with filters
- [x] MCP: `entity_as_of`, `search_audit`

### P3.5 — AgentLab production recipes (tested, not vapor)

- [ ] Swarm manager / compliance auditor / benchmarks — **deferred** (not product core)

### P3.6 — Memory depth

- [ ] Per-workspace connectors, conflict policy, pgvector — **deferred**

### P3 status: **CORE DONE** (v0.7.0) — AgentLab recipes + memory depth later

---

## P4 — Ecosystem, adoption & later

> **Goal:** grow without losing the spine. Ship only when P0–P2 are solid.

### P4.1 — CRM importers

- [x] HubSpot one-shot import (contacts, companies, deals, notes)
- [x] Salesforce, Pipedrive, Attio importers
- [x] Generic mapped import + dry_run
- [x] Mapping UI out of scope — agent-driven ([docs/IMPORTS.md](./docs/IMPORTS.md))

### P4.2 — Custom objects (moldable model)

- [x] Workspace-defined object types + field defs
- [x] Generic CRUD REST + MCP `search_records` / `upsert_record` / `create_object_type`
- [x] Optional `related_entity_type` / `related_entity_id` link to core CRM
- [ ] First-class relationship graph edges for custom types (use free-form graph for now)

### P4.3 — Vertical extensions (REVA / manufacturing optional)

- [x] **Explicit non-goal for core product** — use custom objects / webhooks externally
- [ ] Installable field packs (optional later)

### P4.4 — Install & distribution stretch

- [x] Fly.io / Render sketches ([docs/DEPLOY.md](./docs/DEPLOY.md))
- [x] Operator CLI (`python -m app` / `nakatomi`) — health, protocols, check-config
- [x] SSO (Google / GitHub) — optional ([docs/SSO.md](./docs/SSO.md))
- [ ] Homebrew / full PyPI package polish
- [ ] Cloudflare edition parity matrix

### P4.5 — Service CRM (only if demand)

- [ ] Tickets + SLA — **out of scope** until demanded

### P4.6 — Territories, teams, queues

- [ ] Enterprise sales motion — **out of scope** for default path

### P4 status: **CORE DONE** (v0.8.0) — importers + custom objects; SSO/CLI in v1.0

---

## Priority decision matrix

When a new idea arrives, score it:

| Question | Prefer ship | Prefer reject / defer |
| --- | --- | --- |
| Does it help an **agent** act safely? | Yes | Only helps a human UI |
| Is it **structured truth** (spine)? | Yes | Soft intelligence we can’t win |
| Can it be done with **existing primitives**? | Prefer compose | New micro-tool sprawl |
| Does it improve **MCP / A2A / ACP**? | Yes | Protocol-unaware one-off |
| Can we **test** it in CI? | Yes | Untestable magic |
| Does it violate **non-goals**? | No | Marketing suite, rich UI, deep email client |

---

## Tracking & versioning

| Milestone | Exit criteria |
| --- | --- |
| **v0.4 — Trust** | P0 done; CI green; scoped keys; HITL approvals |
| **v0.5 — Protocols** | **Shipped** — A2A card + task runtime; ACP context pack; compound MCP tools; `/discovery` |
| **v0.6 — Spine** | **Shipped** — leads+convert; views; deal roles; quotes; company merge/hierarchy |
| **v0.7 — Ops** | **Shipped** — jobs; dead letters; time-travel; policies |
| **v0.8 — Ecosystem** | **Shipped** — multi-CRM import; custom objects |
| **v1.0 — Production** | **Shipped** — optional OTel; optional SSO; CLI; protocol SLA; docs freeze; SECRET_KEY prod guard |

SemVer: breaking MCP/A2A/ACP contract changes require major bump + sunset window announced in `/schema` and CHANGELOG.

---

## Open questions (resolve during P0–P1)

1. **A2A binding:** pure REST vs JSON-RPC transport — follow whatever the current LF A2A reference SDKs standardize; abstract behind an interface.
2. **ACP naming in public APIs:** `/acp/context` vs `/context/pack` — pick one, alias the other.
3. **Email default:** require approval policy on `send_email` for new workspaces? (Recommended: yes.)
4. **Custom objects timing:** hard-gate behind v0.6 or allow experimental flag earlier?
5. **Cloudflare edition:** track parity in a separate matrix file or single monorepo later?

---

## Changelog of this roadmap

| Date | Change |
| --- | --- |
| 2026-08-07 | **v1.0 shipped** — protocol SLA, optional OTel + SSO, operator CLI, docs freeze. |
| 2026-08-06 | Rebuilt as P0–P4 roadmap from competitive/agent research; added full **MCP + A2A + ACP** protocol stack; preserved shipped foundation; defined v0.4–v1.0 milestones. |

PRs welcome. Prefer small vertical slices that leave CI greener and agents safer than large untested surfaces.
