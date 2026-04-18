# Railway 1-Click Template

Nakatomi ships a Railway deploy button so anyone can spin up their own
instance in under two minutes without touching a CLI.

There are **two** layers to this:

1. **The generic button** — points at
   `https://railway.com/new/template?template=<github-repo>`. Works
   from the repo as-is; Railway reads `railway.toml` + the Dockerfile
   and provisions the service. Users still have to add a Postgres
   plugin and fill `SECRET_KEY` by hand.
2. **The published template** — once Matt (or any maintainer) clicks
   *Publish as Template* on a known-good deployment in the Railway
   dashboard, Railway mints a share code (e.g. `nakatomi-crm`). The
   button URL swaps to
   `https://railway.com/template/<CODE>`, and clicking it pre-wires
   Postgres, generates `SECRET_KEY`, and runs the Dockerfile in one
   shot.

The README button is currently wired to option (1). When option (2)
is ready, swap the URL in [`README.md`](../README.md) — the badge
image and anchor text stay the same.

---

## How to publish the template (one-time, Railway dashboard)

1. Open the **Nakatomi** project in Railway (the one already running
   a healthy deployment — see [DEPLOYMENT_LESSONS.md](./DEPLOYMENT_LESSONS.md)
   for what "healthy" means).
2. Project settings → **Publish as Template**.
3. Template name: `Nakatomi CRM`. Description: *A headless,
   agent-native CRM. REST + MCP. Built for Claude, ChatGPT, Cursor,
   Perplexity.*
4. Pick both services (the app + the attached Postgres). Railway
   will infer the `DATABASE_URL` link automatically.
5. For each **variable** below, set a default (or mark required):

| Variable | Default | Required? | Notes |
|---|---|---|---|
| `SECRET_KEY` | — (generate) | ✅ | Mark as *Generate secret*. Railway will run `openssl rand -hex 32` per install. |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | ✅ | Linked variable — do NOT mark required user input. |
| `ENVIRONMENT` | `production` | ✅ | |
| `LOG_LEVEL` | `INFO` | | |
| `JWT_EXPIRE_MINUTES` | `60` | | |
| `STORAGE_BACKEND` | `local` | | Change to `s3` if the user also supplies S3 keys. |
| `STORAGE_LOCAL_PATH` | `/app/data/files` | | Matches the mounted volume. |
| `S3_BUCKET` | (empty) | | |
| `S3_REGION` | `us-east-1` | | |
| `S3_ENDPOINT_URL` | (empty) | | Leave blank for AWS; set for Cloudflare R2, Backblaze, MinIO. |
| `S3_ACCESS_KEY` | (empty) | | |
| `S3_SECRET_KEY` | (empty, sensitive) | | |
| `MEMORY_CONNECTORS` | (empty) | | Comma-separated: `docdeploy,supermemory,gbrain`. |
| `DOCDEPLOY_API_KEY` | (empty, sensitive) | | |
| `SUPERMEMORY_API_KEY` | (empty, sensitive) | | |
| `GBRAIN_MCP_URL` | (empty) | | |
| `GBRAIN_TOKEN` | (empty, sensitive) | | |
| `DASHBOARD_ENABLED` | `false` | | Don't turn on in public deployments unless the dashboard is behind auth. |
| `CORS_ORIGINS` | `*` | | |
| `WEBHOOK_WORKER_ENABLED` | `true` | | |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | | |
| `WEBHOOK_MAX_RETRIES` | `3` | | |

6. Add a **volume**: mount `/app/data` in the nakatomi service so
   `STORAGE_BACKEND=local` uploads survive redeploys.
7. Set the **healthcheck path** to `/health` and the **healthcheck
   timeout** to `300` (cold-start budget — see
   [§7 in DEPLOYMENT_LESSONS](./DEPLOYMENT_LESSONS.md#7--default-healthchecktimeout-30s-is-too-tight-for-cold-starts)).
8. Publish. Copy the share code.
9. Update `README.md`:

   ```diff
   - [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2Fmrdulasolutions%2FNakatomiCRM)
   + [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/<SHARE_CODE>)
   ```

10. Commit + push.

---

## What a user sees when they click the button

With the published template:

1. Railway login / signup.
2. Review panel: one nakatomi service + one Postgres. All required
   vars pre-filled; `SECRET_KEY` generated. User only picks a project
   name + region.
3. Deploy. 60–90s later, `https://<name>.up.railway.app/health`
   returns `{"ok":true}` and `/mcp/` speaks streamable HTTP.
4. To create the first workspace + user + API key, the user SSHes in
   (or opens the Railway shell) and runs:

   ```bash
   python -m scripts.seed --email you@example.com \
     --password 'hunter2hunter2' \
     --workspace-name "My Workspace" --workspace-slug mine
   ```

   The script prints a ready-to-use API key.

---

## Notes for maintainers

- **Updating the template** is a separate flow from updating the repo.
  A `git push` to `main` does **not** auto-republish the template. You
  need to re-publish (or click *Sync from Project*) in the dashboard.
- **Env var drift** will silently break the template: if we add a new
  required env in [`app/config.py`](../app/config.py), the template's
  variable list needs to match. The [`.env.example`](../.env.example)
  file is the source of truth — diff it against this doc before
  re-publishing.
- **Postgres version**: the template pins `postgres:16` because our
  migrations use JSONB and `pg_trgm`. Don't let the template drift to
  15 or earlier.
- **Auth story**: the template deploys bearer + OAuth 2.1 simultaneously.
  Claude Code / Cursor connect via bearer; Claude Desktop uses OAuth.
  Both are covered in [`README.md § Authentication`](../README.md#authentication).
