# Deployment Lessons Learned

> First real Railway deploy on 2026-04-18 cascaded through **eleven** distinct
> issues before `/health` returned 200 cleanly and `/mcp` mounted. Every one
> of them was invisible to CI (CI uses `Base.metadata.create_all` directly
> and runs against a postgres service container — the production path is
> different in a half-dozen small ways).
>
> If you're the next person deploying Nakatomi to Railway (or Fly, Render,
> Kubernetes — most apply broadly), read this **first**.

---

## The checklist (if you're in a hurry)

Before `railway up`, verify:

- [ ] `railway.toml` `startCommand` is wrapped in `sh -c` (see §1)
- [ ] `startCommand` uses `python -u` for unbuffered stdout (§8)
- [ ] `startCommand` has `&& exec uvicorn …` so signals propagate
- [ ] `healthcheckTimeout = 300` in `[deploy]` (§7)
- [ ] `PORT=8080` set as a service variable (§11)
- [ ] `DATABASE_URL=${{Postgres.DATABASE_URL}}` points at exactly **one** Postgres (§4)
- [ ] No duplicate Postgres services — check `railway status --json` (§4)
- [ ] `requirements.txt` has `mcp>=1.14` and a compatible `pydantic` (§5, §6)
- [ ] Alembic migrations are idempotent (each inspects before mutating) (§2)
- [ ] `Settings.DATABASE_URL` rewrites `postgres://` → `postgresql+psycopg://` (§3)

Run `railway up --service nakatomi --detach`, then watch:

```bash
railway logs --service nakatomi --deployment
```

You should see: migrations → `Started server process` → `Uvicorn running on http://0.0.0.0:8080` → `MCP server mounted at /mcp` → a `GET /health HTTP/1.1" 200 OK`. Total: ~30–60s cold.

---

## Issue-by-issue

### §1 — `startCommand` doesn't run through a shell

**Symptom**

```
The executable `export` could not be found.
```

No app logs. Healthcheck fails.

**Root cause**

Railway executes `startCommand` as a direct `exec`, not via `/bin/sh`. That
means `&&`, `$VAR` expansion, `export`, redirects, `&`, pipes — none of
those work unless you invoke a shell explicitly.

**Fix**

```toml
startCommand = "sh -c 'alembic upgrade head && exec python -u -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}'"
```

`exec` on the final command makes `uvicorn` PID 1 so SIGTERM reaches it.

---

### §2 — `Base.metadata.create_all()` in migration 0001 broke every migration that followed

**Symptom**

```
psycopg.errors.DuplicateColumn: column "status" of relation "webhook_deliveries" already exists
```

Fresh Railway DB + `alembic upgrade head` → crash in migration 0003.

**Root cause**

Migration 0001 uses `Base.metadata.create_all(bind)` which reflects the
**current** model definition — not what existed at v0.1.0. So on fresh
installs, 0001 creates tables with columns that 0003/0004/0005 then try to
add. ALTER TABLE + ADD COLUMN on a column that already exists = duplicate.

This was invisible in CI because tests use `create_all` directly and skip
alembic entirely.

**Fix**

Make every structural migration idempotent:

```python
def _cols(table): return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}

def upgrade():
    cols = _cols("webhook_deliveries")
    to_add = [col for col in candidates if col.name not in cols]
    if to_add:
        with op.batch_alter_table("webhook_deliveries") as batch:
            for col in to_add: batch.add_column(col)
```

See [`alembic/versions/0003_durable_webhooks.py`](../alembic/versions/0003_durable_webhooks.py),
[`0004`](../alembic/versions/0004_api_key_rate_limit.py),
[`0005`](../alembic/versions/0005_custom_fields.py).

**Lesson for the future**

Never use `create_all` inside a migration. Migration 0001 should use
explicit `op.create_table(...)` calls for exactly the tables that existed
at v0.1.0. Using `create_all` as a shortcut works for the very first
deploy but leaves a landmine for every subsequent migration against a
fresh DB.

---

### §3 — Railway's `DATABASE_URL` scheme doesn't match SQLAlchemy's default driver

**Symptom (would have been)**

```
sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres
```
or
```
ModuleNotFoundError: No module named 'psycopg2'
```

**Root cause**

Railway (and Heroku, Fly, Render) emit `DATABASE_URL=postgres://...` or
`postgresql://...`. SQLAlchemy infers the driver from the scheme:

- `postgres://` — legacy, often not loadable
- `postgresql://` — resolves to `psycopg2` (the old driver)
- `postgresql+psycopg://` — resolves to `psycopg` v3 (what we ship)

We use psycopg v3. Railway gives us plain `postgresql://`. No match.

**Fix**

Rewrite in the config layer so every caller sees the right URL:

```python
@field_validator("DATABASE_URL", mode="before")
@classmethod
def _normalize_db_url(cls, v):
    if v.startswith("postgres://"):
        return "postgresql+psycopg://" + v[len("postgres://"):]
    if v.startswith("postgresql://") and "+" not in v.split("://",1)[0]:
        return "postgresql+psycopg://" + v[len("postgresql://"):]
    return v
```

Lives in [`app/config.py`](../app/config.py). Portable across Heroku,
Fly, Render, Railway.

---

### §4 — `railway init` auto-provisioned a second Postgres

**Symptom**

```
$ railway status --json | jq '.services.edges[].node.name'
"Postgres"
"Postgres-PT3C"
"nakatomi"
```

Two Postgres services. `DATABASE_URL` resolution became ambiguous.

**Root cause**

`railway init --name Nakatomi` auto-added `Postgres`. Our follow-up
`railway add -d postgres` created a second one (`Postgres-PT3C`). The CLI
didn't warn.

**Fix**

Just skip the explicit `railway add -d postgres` after `railway init`
(at least in our workspace configuration). Or delete the duplicate via
the Railway web UI — the CLI doesn't have a `service delete` command.

**Lesson**

After `railway init`, always run `railway status --json` and inspect
services before adding more.

---

### §5 — mcp 1.2.0 predates remote HTTP transport

**Symptom**

```
WARNING nakatomi MCP server failed to mount: 'FastMCP' object has no attribute 'sse_app'
```

REST came up fine. `/mcp` returned 404.

**Root cause**

The `mcp` Python SDK at 1.2.0 only exposed `run_sse_async`. The modern
`streamable_http_app()` and `sse_app()` methods landed around 1.14.

**Fix**

```txt
-mcp==1.2.0
+mcp==1.27.0
```

---

### §6 — mcp 1.27 requires pydantic ≥ 2.11 (transitive conflict)

**Symptom**

Railway build:

```
ERROR: Cannot install -r requirements.txt (line 1), ... and pydantic==2.10.3
because these package versions have conflicting dependencies.

    mcp 1.27.0 depends on pydantic<3.0.0 and >=2.11.0
```

**Root cause**

Upgraded `mcp` without re-resolving transitive constraints. Our `pydantic`
pin was 2.10.3.

**Fix**

```txt
-pydantic==2.10.3
+pydantic==2.11.0
```

No API changes we use — field_validator, ConfigDict, Field, model_dump
all work the same.

**Lesson**

When bumping any dep, run `pip install -r requirements.txt` in a fresh
env locally first. The Docker build catches it too, but only after a
15-second cache miss.

---

### §7 — Default healthcheckTimeout (30s) is too tight for cold starts

**Symptom**

```
Attempt #1 failed with service unavailable. Continuing to retry for 25s
Attempt #2 failed with service unavailable. Continuing to retry for 19s
Attempt #3 failed with service unavailable. Continuing to retry for 7s
1/1 replicas never became healthy!
Healthcheck failed!
```

The app was about to come up — migrations took ~20s, uvicorn boot another
10–15s. We exceeded 30s.

**Fix**

```toml
[deploy]
healthcheckTimeout = 300
```

Five minutes is generous but cheap — the healthcheck is a single JSON
return (<100ms) once the app is up, so timeouts only bite when something
is actually wrong.

---

### §8 — Python buffered stdout hid every debug print for minutes

**Symptom**

Container logs:

```
Starting Container
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

Then nothing. For minutes. No error, no startup banner. We thought alembic
was hanging.

**Root cause**

Python's stdout is block-buffered when attached to a pipe (Railway's log
pipe). `print()` and stdlib `logging` output sits in the buffer until
flushed — which effectively never happens until the process exits.

**Fix**

Add `-u` (unbuffered) when invoking Python:

```toml
startCommand = "sh -c 'alembic upgrade head && exec python -u -m uvicorn app.main:app ...'"
```

Alternative: set `PYTHONUNBUFFERED=1` env var.

---

### §9 — `railway logs --deployment <id>` needs the full UUID

**Symptom**

```
$ railway logs d6b886e7 --service nakatomi --deployment
Deployment not found
```

Shortened UUIDs (as the Railway UI displays) don't work in the CLI.

**Fix**

Use the full UUID from `railway status --json`:

```bash
railway logs d6b886e7-c9bc-41a8-966c-680ba0cb2a1b --service nakatomi --deployment
```

Note the current CLI syntax treats the deployment ID as a **positional**
argument, not a flag value:

```
railway logs [DEPLOYMENT_ID] [--build | --deployment]
```

---

### §10 — `railway up --detach` returns before the deploy promotes

**Symptom**

Build log says `Healthcheck succeeded!` but production URL keeps serving
the **old** app. For 30–60s after build completion.

**Root cause**

Railway builds → runs replicas → waits for healthcheck → marks deploy as
active. `railway up --detach` returns after upload, not after promotion.
The old deployment keeps serving traffic until the new one is "active".

**Fix**

Check `railway status --json` for `activeDeployments[0].id` vs
`latestDeployment.id`. They're different during the promotion window. The
deploy is fully live when they match:

```bash
railway status --json | jq '.environments.edges[0].node.serviceInstances.edges[]
  | select(.node.serviceName=="nakatomi")
  | {latest: .node.latestDeployment.id, active: .node.activeDeployments[0].id}'
```

---

### §11 — The "Application not found" 200 response

**Symptom**

```
$ curl -i https://nakatomi-production.up.railway.app/health
HTTP/2 200
content-type: application/json

{"status":"error","code":404,"message":"Application not found","request_id":"..."}
```

HTTP 200 with a body that says 404. Came from Railway's edge, not our app.

**Root cause**

Railway's proxy returns this shape during the window between when a
domain is assigned and when the service is actually routing. Also shows
up briefly during deploy promotions.

**Fix**

None needed — it clears itself once the new deployment is live (§10). But
don't write monitor checks that only look at HTTP status; also check the
body or a specific key in the response:

```bash
curl -sS $BASE/health | jq -e '.ok == true'
```

---

## What we're changing going forward

- The `install.sh` + `docker-compose.yml` local path is documented and
  tested. The Railway path was assumed to "just work" from the Dockerfile
  because the Dockerfile works locally. **That assumption was wrong.**
  Every new cloud target needs its own shakedown.
- All future migrations will be idempotent by default. There's a mental
  checklist in [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) (to be added).
- Our tests should include at least one test that runs alembic `upgrade
  head` against a clean DB, so migration-ordering bugs fail CI instead of
  first deploy. That's a v1.1 roadmap row.
- `requirements.txt` should carry a comment on top-level deps explaining
  why that version, so the next `pip install -U` doesn't break silently.

---

## What we'll do differently the next time

1. **Dry-run the deploy checklist against staging before touching prod.**
   Even on a brand-new project, spin up a throwaway Railway project, walk
   through these 11 items, verify `/health` returns `{"ok":true,...}`,
   then tear it down and deploy for real.
2. **Copy this checklist into a GitHub Issue template** for
   "deploy-to-new-environment", so it's one click away for every target.
3. **Don't trust `railway up --detach`'s "Build Logs" URL as a success
   signal.** It means the upload succeeded; not that the deploy is live.
   Wait for `activeDeployments[0].id` to match `latestDeployment.id`
   before declaring victory.
