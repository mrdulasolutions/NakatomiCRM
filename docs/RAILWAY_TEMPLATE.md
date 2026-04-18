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

---

## Upgrading file storage to Railway Bucket (optional)

The template provisions Nakatomi with `STORAGE_BACKEND=local`, writing
uploads to `/app/data/files` on a mounted volume. That's durable
enough for most deploys. If you want the same durability guarantees
as object storage — cross-region replication, multi-replica scale-out,
no volume to baby-sit — swap to a **Railway Bucket**:

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
