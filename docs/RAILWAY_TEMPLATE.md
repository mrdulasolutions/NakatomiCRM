# Railway 1-Click Template

Live at **<https://railway.com/deploy/nakatomicrm>**. Clicking the
Deploy button in [`README.md`](../README.md) drops the visitor onto
that page with Postgres pre-provisioned, `SECRET_KEY` auto-generated,
and every other env var pre-filled — so the install is literally
*name your project → click Deploy*.

The button was previously wired to the generic
`railway.com/new/template?template=<repo>` URL, which worked but
required users to add Postgres and paste a `SECRET_KEY` by hand. That
fallback is still in git history if we ever need to go back to it.

## Live status (2026-09-25)

| Piece | Status |
| --- | --- |
| One-click URL | https://railway.com/deploy/nakatomicrm (**PUBLISHED**) |
| Demo / source project | https://railway.com/project/f5806f53-6506-4dfc-8b9e-6dd826ee46d9 (`NakatomiCRM`) |
| Public demo domain | https://nakatomi-production.up.railway.app |
| App git | `mrdulasolutions/NakatomiCRM@main` (Dockerfile + `railway.toml`) |
| Marketplace metadata | Sync env vars + republish when [`.env.example`](../.env.example) changes (see checklist below) |
| Code on new installs | Pulled from **GitHub `main`** at deploy time — keep `main` green |

## Refresh the published template after a release

The template uses GitHub `main`. Publishing a GitHub tag alone does not
change its deployment source.

1. Confirm the intended release commit is on `main` and GitHub Actions is green.
2. Deploy that revision to staging. Check `/health` for the release version,
   run `python -m app check-config`, and verify database migrations and storage.
3. Verify discovery over HTTPS and complete an authenticated, read-only MCP
   tool call. Use a disposable workspace to check archive download and restore
   when the release includes those features.
4. Compare the template variables and service graph with staging. Keep
   generated secrets, the Postgres reference, and the storage configuration
   specific to each installation. Keep dashboard and memory settings at their
   reviewed public-deployment defaults.
5. In Railway, update the template configuration and publish the overview in
   [RAILWAY_TEMPLATE_README.md](./RAILWAY_TEMPLATE_README.md). Verify the
   public listing and perform a fresh template install before promoting it.

Railway can notify existing template users about GitHub source updates.
Users choose when to apply those updates. See the [Railway template update
documentation](https://docs.railway.com/templates/updates).

---

## Upgrading file storage to Railway Bucket (optional)

The published template lists a **Nakatomi Files** bucket. Verify the app service
is connected to it before relying on object storage. For an existing local
storage deployment, use the following configuration to switch to the bucket:

1. In your Railway project, click **+ New → Bucket**. Name it `nakatomi-files` (or similar).
2. On the nakatomi service, paste these as **reference variables** (Railway auto-resolves them at deploy time — rotations flow through):
   - `S3_BUCKET` → `${{ Nakatomi Files.BUCKET }}`
   - `S3_ACCESS_KEY` → `${{ Nakatomi Files.ACCESS_KEY_ID }}`
   - `S3_SECRET_KEY` → `${{ Nakatomi Files.SECRET_ACCESS_KEY }}`
   - `S3_ENDPOINT_URL` → `${{ Nakatomi Files.ENDPOINT }}`
   - `S3_REGION` → `${{ Nakatomi Files.REGION }}`
3. Flip `STORAGE_BACKEND=s3` on the nakatomi service.
4. Redeploy. New uploads go to the Bucket; old files under `/app/data/files` stay on the volume (no automatic migration — copy them over if you care).

> Naming gotcha: Railway exposes the bucket's name under the key
> `BUCKET` (not `BUCKET_NAME` or `NAME`). Use the reference form above
> and you don't have to memorize it.

Railway Buckets are S3-compatible under the hood, so Nakatomi's
existing `s3` backend talks to them with zero code changes. No AWS
account or R2 setup required — it's all inside Railway.

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
| `MEMORY_CONNECTORS` | (empty) | | Keep empty on shared deployments pending workspace-isolation validation. |
| `DOCDEPLOY_API_KEY` | (empty, sensitive) | | |
| `SUPERMEMORY_API_KEY` | (empty, sensitive) | | |
| `GBRAIN_MCP_URL` | (empty) | | |
| `GBRAIN_TOKEN` | (empty, sensitive) | | |
| `DASHBOARD_ENABLED` | Set `false` on public deployments | | Session sign-in is pending. Validate the dashboard on staging before enabling it publicly. |
| `BOOTSTRAP_TOKEN` | (empty, sensitive) | | Recommended when the deploy URL may sit idle before first claim (`?token=`). |
| `API_KEY_RATE_LIMIT_PER_MINUTE` | `0` | | Recommend `120` in production (`check-config` warns when `0`). |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `60` | | Per endpoint and source IP for login, OAuth authorization and registration, and bootstrap. |
| `CORS_ORIGINS` | `*` | | Prefer explicit origins in production. |
| `WEBHOOK_WORKER_ENABLED` | `true` | | |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | | |
| `WEBHOOK_MAX_RETRIES` | `3` | | |
| `PUBLIC_BASE_URL` | (empty) | | Set to the public HTTPS origin after first deploy (SSO / OAuth redirects). |
| `OTEL_ENABLED` | `false` | | Optional OpenTelemetry ([OBSERVABILITY.md](./OBSERVABILITY.md)). |
| `OTEL_SERVICE_NAME` | `nakatomi` | | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (empty) | | e.g. collector OTLP/HTTP base URL. |
| `SSO_GOOGLE_CLIENT_ID` | (empty) | | Optional human SSO ([SSO.md](./SSO.md)). |
| `SSO_GOOGLE_CLIENT_SECRET` | (empty, sensitive) | | |
| `SSO_GITHUB_CLIENT_ID` | (empty) | | |
| `SSO_GITHUB_CLIENT_SECRET` | (empty, sensitive) | | |
| `SSO_AUTO_CREATE_WORKSPACE` | `true` | | First SSO login creates a personal workspace. |

6. Add a **volume**: mount `/app/data` in the nakatomi service so
   `STORAGE_BACKEND=local` uploads survive redeploys.
7. Set the **healthcheck path** to `/health` and the **healthcheck
   timeout** to `300` (cold-start budget — see
   [§7 in DEPLOYMENT_LESSONS](./DEPLOYMENT_LESSONS.md#7--default-healthchecktimeout-30s-is-too-tight-for-cold-starts)).
8. Publish. Railway issues a share URL — ours is
   <https://railway.com/deploy/nakatomicrm>.
9. Update the README button to point at that URL (done).
10. Commit + push.

---

## What a user sees when they click the button

With the published template:

1. Railway login / signup.
2. Review panel: one nakatomi service + one Postgres. All required
   vars pre-filled; `SECRET_KEY` generated. User only picks a project
   name + region.
3. Deploy. 60–90s later, `https://<name>.up.railway.app/health`
   returns `{"ok":true,"version":"1.0.6",…}` and `/mcp/` speaks streamable HTTP.
4. Open the public URL: **branded welcome** at `/` creates the first workspace,
   owner account, and API key in one form (key shown once). OAuth authorize
   uses the same Nakatomi Plaza UI at `/oauth/authorize`.
5. Set `PUBLIC_BASE_URL` to your Railway HTTPS origin; run
   `python -m app check-config` and set `BOOTSTRAP_TOKEN` / rate limits if the
   URL may sit public before claim (see production table in [DEPLOY.md](./DEPLOY.md)).

   CLI alternative (Railway shell):

   ```bash
   python -m scripts.seed --email you@example.com \
     --password 'hunter2hunter2' \
     --workspace-name "My Workspace" --workspace-slug mine
   ```

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
