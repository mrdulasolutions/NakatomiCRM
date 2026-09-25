# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/).

## [Unreleased]

## [1.0.10] — 2026-09-25 — Roadmap stretch (P1/P2/P3/P5–P6)

### Added

- **MCP:** Resource templates `crm://contact|deal|company/{id}`; versioned **`mcp_tools`** / **`mcp_resources`** on `GET /schema`.
- **P2.6:** Custom field runtime validation on entity PATCH (422 + suggestions).
- **P2.7:** Forecast `by_commit`, `by_currency`, `compare_prior` trend.
- **P3.2:** Auto-promote ingest payloads **>200** records to async jobs.
- **Docs:** [WORKFORCE-DEMO.md](./docs/demos/WORKFORCE-DEMO.md), [AGENTLAB-RECOVERY.md](./docs/AGENTLAB-RECOVERY.md), [CLOUDFLARE_PARITY.md](./docs/CLOUDFLARE_PARITY.md).

### Changed

- **ROADMAP:** P5.7 / P6.4 demo scripts marked shipped.

## [1.0.9] — 2026-09-25 — Dashboard login visibility

### Fixed

- **`/dashboard`** login panel used inverted `hidden` logic, so sign-out hid the API key form and refresh could re-auth from a surviving cookie while the UI looked logged out.

## [1.0.8] — 2026-09-25 — Dashboard sign out

### Fixed

- **Sign out** clears `sessionStorage` and the API-key cookie with matching `Secure`/`path` attributes (HTTPS), and returns to the login panel without a broken reload loop.

## [1.0.7] — 2026-09-25 — Dashboard login panel visibility

### Fixed

- Hide the **Connect your API key** panel when authenticated (`display:flex` no longer overrides the HTML `hidden` attribute).

## [1.0.6] — 2026-09-25 — Dashboard API key persistence

### Fixed

- **`/dashboard`** no longer clears the saved API key on every failed API call; shows an inline error instead (clears only on HTTP 401).
- API key stored with **`path=/`**, `sessionStorage` fallback, and inline connect (no reload loop).

## [1.0.5] — 2026-09-25 — Branded audit dashboard

### Changed

- **`/dashboard`** uses Nakatomi Plaza branding (shared `brand_pages` stylesheet with welcome/OAuth).
- **`DASHBOARD_ENABLED`** auto-on in `development` / `dev` / `local` when unset; branded HTML when disabled instead of JSON 404.
- Docker Compose omits a false default so dev compose picks up the development auto-enable.

### Docs

- `nakatomi-dashboard` skill notes dev default and Plaza UI.

## [1.0.4] — 2026-09-25 — Email secrets at rest

### Added

- **EmailConfig credential encryption** — IMAP/SMTP passwords stored with
  Fernet (`enc:v1:` prefix); legacy plaintext rows still work until re-saved.
- Alembic `0016_email_secrets_widen` widens password columns to `Text`.

### Changed

- Rotating `SECRET_KEY` requires re-saving email config (documented in DEPLOY).

## [1.0.3] — 2026-09-25 — Production hardening

### Added

- **`AUTH_RATE_LIMIT_PER_MINUTE`** — in-process rate limit on
  `POST /auth/login`, `/auth/signup`, and `/bootstrap` (0 = disabled).
- **`BOOTSTRAP_TOKEN`** in `Settings` / `.env.example` (replaces raw env-only read).
- **`python -m app check-config`** production warnings: CORS `*`, disabled API
  key limits, missing bootstrap token, SSO without `PUBLIC_BASE_URL`.

### Changed

- [SECURITY.md](./SECURITY.md) — auth/bootstrap brute force mitigated when
  `AUTH_RATE_LIMIT_PER_MINUTE` is set.

## [1.0.2] — 2026-09-25 — Supply chain

### Added

- Dependabot for pip and GitHub Actions (weekly).
- CI **`pip-audit`** step on `requirements.txt`.

### Changed

- GitHub Actions: bump `actions/checkout` and `actions/setup-python`.

## [1.0.1] — 2026-09-25 — CI green

### Added

- **MCP custom fields** — `list_custom_fields`, `create_custom_field`,
  `update_custom_field`, `delete_custom_field` (owner/admin for mutations).
- **MCP** `list_object_types`; `describe_schema` now returns workspace
  `custom_fields` + `custom_object_types` + protocol SLA block.

### Fixed

- **Ruff** — remove unused imports and format the tree (CI lint job).
- **Mypy** — email IMAP payload typing and calendar ICS update paths.

## [1.0.0] — 2026-08-07 — Production (v1.0 polish)

### Added

- **Protocol version SLA** — contract versions for REST/MCP/A2A/ACP (`1.0`),
  90-day sunset policy, `scheduled_sunsets` list. Exposed on `GET /schema`,
  `GET /discovery`, `GET /health`. Docs: `docs/PROTOCOL_SLA.md`.
- **Optional OpenTelemetry** — `OTEL_ENABLED` soft-import hooks (FastAPI /
  httpx / SQLAlchemy instrumentors when installed; OTLP/HTTP exporter).
  Docs: `docs/OBSERVABILITY.md`.
- **Optional SSO** — Google + GitHub OAuth for human operators
  (`/auth/sso/...`). Migration `0015_v1_sso` (nullable `password_hash`,
  `sso_provider` / `sso_subject`). Docs: `docs/SSO.md`.
- **Operator CLI** — `python -m app` / `nakatomi`: `version`, `protocols`,
  `health`, `check-config`.
- **Production SECRET_KEY guard** — refuse boot when `ENVIRONMENT=production`
  and the secret is a known default or under 32 chars.

### Changed

- App version **1.0.0**; stability tier **stable**.
- `/health` includes `stability`, `protocols`, and `otel` status.

## [0.8.0] — 2026-08-06 — Ecosystem (P4)

### Added

- **CRM importers** — `POST /import/crm` for `hubspot`, `salesforce`,
  `pipedrive`, `attio`, `generic` (dry_run + upsert by external_id).
  MCP `import_crm`. Docs: `docs/IMPORTS.md`.
- **Custom objects** — workspace-defined types + records CRUD under
  `/custom-objects`. MCP `create_object_type`, `upsert_record`,
  `search_records`. Docs: `docs/CUSTOM_OBJECTS.md`.
- Deploy sketches for Fly/Render: `docs/DEPLOY.md`.
- Migration `0014_p4_import_custom_objects`. Version `0.8.0`.

## [0.7.0] — 2026-08-06 — Agent ops (P3)

### Added

- **Policies** — `GET/PUT /policies` declarative rules in
  `workspace.data.policies` (approvals, required_fields, block,
  auto_tasks). Enforced on deal PATCH + lead create. MCP `list_policies`.
- **Jobs** — `Job` table + `POST/GET /jobs`, cancel; types
  `ingest|export|merge|custom`; async thread runner. MCP `start_job` /
  `get_job`. Migration `0013_p3_jobs`.
- **Webhook dead letters** — `GET /webhooks/dead-letters`,
  `POST /webhooks/dead-letters/{id}/replay`.
- **Forensics** — `GET /audit` search; `GET /entities/{type}/{id}/as-of?ts=`.
  MCP `search_audit`, `entity_as_of`.
- Version `0.7.0`.

## [0.6.0] — 2026-08-06 — CRM spine (P2)

### Added

- **Leads** — full CRUD, status lifecycle, `POST /leads/{id}/convert`
  (contact + optional company/deal), email duplicate check,
  MCP `create_lead` / `search_leads` / `convert_lead`.
- **Deal participants** — buying-committee roles on deals
  (`champion`, `economic_buyer`, `legal`, `user`, `influencer`, `other`).
- **Account hierarchy** — `Company.parent_company_id`.
- **Company merge** — `POST /companies/merge` (rewrite FKs, soft-delete loser).
- **Contact channels** — extra emails/phones via `/contacts/{id}/channels`.
- **Saved views** — filter DSL, seed defaults (`open_deals`, `stale_deals`,
  `new_leads`, `tasks_due_this_week`, `pending_approvals`),
  `POST /views/{slug}/run`, MCP `list_views` / `run_view`.
- **Quotes** — versioned per deal, line-item snapshots, status transitions,
  optional deal amount sync on accept; MCP `create_quote` / `set_quote_status`.
- Migration `0012_p2_crm_spine`. Version `0.6.0`.

## [0.5.0] — 2026-08-06 — Protocols (P1)

### Added

- **A2A Agent Card (dynamic)** at `/.well-known/agent-card.json` and
  legacy `/.well-known/agent.json` — skills, securitySchemes, request
  base URL, Nakatomi transport extensions.
- **A2A REST task runtime** — `POST/GET /a2a/tasks`, messages,
  complete/fail/cancel/input-required; lifecycle
  `submitted|working|input_required|completed|failed|canceled`.
  HITL via linked `ApprovalRequest` (approve resumes, reject fails).
  Migration `0011_a2a_tasks`.
- **ACP context packs** — `GET /acp/context` (+ `?sections=`), ETag /
  304, MCP `load_context`. Docs: `docs/ACP.md`.
- **`GET /discovery`** — single index linking OpenAPI, schema, MCP,
  A2A, ACP, OAuth, health.
- **Compound MCP tools:** `load_context`, `morning_briefing`,
  `upsert_account_map`, `advance_deal`, `log_interaction`.
- Docs: `docs/A2A.md`, `docs/MCP_PARITY.md`.
- Version `0.5.0`.

## [0.4.0] — 2026-08-06 — Trust (P0 complete)

### Added

- **Capability-scoped API keys.** `ApiKey.scopes` JSONB list
  (`contacts:write`, `email:send`, `admin:keys`, `*`, …). New member
  keys default to agent-safe scopes (write CRM data, no hard-delete,
  no email send, no key admin). Owner/admin keys default to `["*"]`.
  Legacy keys with `null`/empty scopes keep full access.
  Router-level `enforce_resource_scope` on every CRM resource; MCP
  tools check scopes on every call.
- **HITL approvals.** `ApprovalRequest` + `POST /approvals`,
  `GET /approvals`, `POST /approvals/{id}/decide`. Workspace policy
  hook `data.policies.approvals` can force approval on `email.send`.
  MCP tools: `propose_action`, `list_pending_approvals`,
  `decide_approval`.
- **Global Idempotency-Key middleware** for all mutating REST with API
  keys; MCP mutators accept `idempotency_key`. Replay returns
  `Idempotent-Replay: true`.
- **Request IDs + access logs** — `X-Request-Id` on every response;
  structured `method path status ms request_id actor` log lines.
- **`GET /health/deep`** — Postgres readiness check.
- **Alembic migration smoke test** + CI migrate database.
- Migration `0010_scopes_approvals`.

### Changed

- ETHOS + README “What we are / aren’t”: thin email/calendar I/O
  adapters are in-scope; sequence engines and rich UI remain non-goals.
- `llms.txt` documents scopes, approvals, idempotency, health/deep.
- `email:send` requires the `email:send` scope (not just member role).
- Hard-delete requires `resource:delete`.
- `requirements.txt` pin comments; `psycopg[binary]` → 3.2.13.
- Version `0.4.0`.

### Fixed

- Product PATCH audit diffs now use SQLAlchemy history correctly.
- Forecast test sets `status: won` for won deals.
- Email send test patches the router-bound `send_email` symbol.
- Alembic `env.py` honors explicit `sqlalchemy.url` (tests/CLI).

### Added (prior unreleased / v0.3)

- **8 new MCP tools** mirroring the v0.3 surface so agents reach the
  new endpoints natively: `create_product`, `search_products`,
  `add_line_item`, `list_line_items`, `forecast`, `send_email`,
  `add_calendar_feed`, `sync_calendar_feed`.
- **Email adapter (IMAP + SMTP).** Per-workspace `EmailConfig` with
  separate IMAP/SMTP creds; either half can be left blank. `POST
  /email/send` sends via SMTP and persists an `email_outbound`
  activity. Background poller (`EMAIL_POLLER_ENABLED=true`) pulls new
  inbound messages by IMAP UID, matches `From:` to existing contacts
  by email, and persists `email_inbound` activities. Idempotent on
  IMAP UID — re-running the poller never duplicates.
- **Calendar adapter (iCal feeds).** Per-workspace `CalendarFeed` with
  any `.ics` URL (Google, Microsoft, Fastmail, Hostinger, iCloud).
  Background poller (`CALENDAR_POLLER_ENABLED=true`) fetches the feed,
  parses VEVENTs, matches attendees to contacts by email, and creates
  or updates `meeting`-kind activities. Honors `ETag`/`If-None-Match`
  for cheap polls. `POST /calendar/feeds/{id}/sync` runs an on-demand
  sync.
- **Product catalog + deal line items.** `Product` entity (sku unique
  per workspace, soft-deletable) and `DealLineItem` (nested under
  `/deals/{id}/line-items`). Lines snapshot `name` + `unit_price` from
  the catalog at creation so historical deal totals don't drift when
  the catalog changes. Either pass `product_id` (snapshots from
  catalog) or `name`+`unit_price` for an ad-hoc line.
- **Forecast endpoint** — `GET /forecast?period=2026Q2` (or
  `2026-04`, or `custom:2026-04-01:2026-06-30`). Returns totals
  (open / won / lost / weighted), stage breakdown, and owner
  breakdown for the period. Stage probability stored as 0–100 and
  divided once at rollup. Filters: `pipeline_id`, `owner_user_id`.
- **`POST /bootstrap` + welcome page** — first-run flow for a fresh
  Railway deploy. `GET /` on an empty install renders a server-side
  signup form (no JS) that creates user + workspace + admin API key
  in one transaction, then displays the key once. After the first
  user exists, `/bootstrap` returns 409 and `/` reverts to the JSON
  discovery doc. Set `BOOTSTRAP_TOKEN` to require a shared secret.
- **OAuth 2.1 provider** (`/oauth/{register,authorize,token,revoke}` +
  `.well-known/oauth-authorization-server` and `oauth-protected-resource`) so
  Claude Desktop's Custom Connector GUI works out of the box.
- **Durable webhook worker** with `SELECT … FOR UPDATE SKIP LOCKED`, retry
  backoff, and a delivery log viewable at `/webhooks/{id}/deliveries`.
- **Audit diffs** on every mutation (append-only JSONB snapshots).
- **Fuzzy duplicate detection** (`pg_trgm`) + duplicate `merge` for contacts.
- **Custom fields** — workspace-scoped named registry; values land in each
  row's `data` JSONB.
- **Export / import** — portable JSON round-trip. The spine of the
  user-owns-their-data ethos.
- **Per-API-key rate limiting** + `API_KEY_RATE_LIMIT_PER_MINUTE`.
- **Streaming chunked file uploads** (`POST /files` multipart → S3 or local
  volume) — works against Railway Bucket, AWS S3, R2, or MinIO.
- **GBrain memory connector** shipped end-to-end: streamable-HTTP MCP client
  against `${GBRAIN_MCP_URL}` using `put_page` + `query`.
- **MCP `create_pipeline` tool** — build a pipeline and its stages in one
  call (useful for fresh installs and HubSpot-style imports).
- **Railway 1-click template** at <https://railway.com/deploy/nakatomicrm>,
  with the deployment playbook in
  [docs/RAILWAY_TEMPLATE.md](./docs/RAILWAY_TEMPLATE.md).
- **Railway Bucket** support via reference variables
  (`${{ Nakatomi Files.BUCKET }}` etc.) — detailed in
  [docs/RAILWAY_TEMPLATE.md](./docs/RAILWAY_TEMPLATE.md#upgrading-file-storage-to-railway-bucket-optional).
- **Nakatomi Plaza icon** (`public/icon.{svg,png}`) + ASCII art
  (`public/nakatomi.{svg,txt}`), the latter served at `GET /nakatomi.txt`.
- **Deployment lessons** —
  [docs/DEPLOYMENT_LESSONS.md](./docs/DEPLOYMENT_LESSONS.md) covers the 13
  distinct Railway gotchas we cascaded through on first deploy.
- Memory connector framework with `DocDeploy` and `Supermemory` adapters, and a
  `MemoryLink` table for cross-referencing CRM entities ↔ external memories.
- `POST /memory/recall`, `POST /memory/link`, `POST /memory/webhook/{connector}`.
- Ingest adapter framework + `POST /ingest` for CSV, vCard, JSON, and text.
- Local audit dashboard at `/dashboard` (off by default, `DASHBOARD_ENABLED=true`
  to opt in).
- Claude Code skills: `nakatomi-crm` and `nakatomi-dashboard`.
- `llms.txt` served at `/llms.txt`.
- A2A agent card served at `/.well-known/agent.json`.
- `docker-compose.yml` and `install.sh` for one-command local install.
- OSS repo scaffolding: `LICENSE`, `README`, `AUTHORS`, `CONTRIBUTORS`,
  `SECURITY`, `ETHOS`, `CODE_OF_CONDUCT`, `CHANGELOG`, `ROADMAP`.

## [0.1.0] — Initial scaffold

### Added

- FastAPI + Postgres + Alembic + Dockerfile + `railway.toml`.
- Multi-tenant workspaces; user JWT and per-workspace API keys.
- Contacts, Companies, Pipelines/Stages, Deals, Activities, Notes, Tasks.
- Relationship graph with typed edges and BFS neighbor lookup.
- Append-only timeline + append-only audit log.
- HMAC-signed webhooks with retry and delivery log.
- Pluggable file storage (`local` | `s3`).
- Soft delete, cursor pagination, bulk upsert, idempotency scaffolding.
- Self-describing `/schema` manifest.
- MCP server at `/mcp` with 13 agent tools (contacts, companies, deals,
  activities, notes, tasks, relationships, timeline, schema).
- Seed script.
