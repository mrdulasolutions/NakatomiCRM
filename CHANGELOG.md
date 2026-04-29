# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added

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
