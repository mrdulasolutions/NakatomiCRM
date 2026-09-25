# Deploy notes (beyond Railway)

## Docker Compose (default)

```bash
cp .env.example .env   # set SECRET_KEY
docker compose up -d
```

Postgres + app on `:8000`. Files on volume `nakatomi_files`.

## Fly.io (sketch)

```bash
fly launch --dockerfile Dockerfile --no-deploy
fly postgres create
fly secrets set SECRET_KEY=$(openssl rand -hex 32) DATABASE_URL=...
fly deploy
```

Point `DATABASE_URL` at Fly Postgres (`postgresql://` is rewritten to
`postgresql+psycopg://` automatically). Mount a volume for
`STORAGE_LOCAL_PATH` or set `STORAGE_BACKEND=s3`.

## Render

- Web service from Dockerfile
- Managed Postgres → set `DATABASE_URL`
- Disk or S3 for files
- Health check path: `/health`

## Persistence reminder

Nakatomi is **Postgres-only** (no SQLite). Do not point `DATABASE_URL` at sqlite.

## Production checklist (v1.0)

```bash
python -m app check-config
```

| Setting | Notes |
| --- | --- |
| `ENVIRONMENT=production` | Enables SECRET_KEY boot guard |
| `SECRET_KEY` | ≥32 random chars; not a documented default; keys email credential encryption |
| `DATABASE_URL` | Managed Postgres; run `alembic upgrade head` |
| `PUBLIC_BASE_URL` | Canonical HTTPS origin (SSO / OAuth redirects) |
| `BOOTSTRAP_TOKEN` | Shared secret for `?token=` on first-run bootstrap (recommended on public URLs) |
| `API_KEY_RATE_LIMIT_PER_MINUTE` | Recommend `120` for agent keys in production |
| `AUTH_RATE_LIMIT_PER_MINUTE` | Recommend `30` for `/auth/login`, `/auth/signup`, `/bootstrap` |
| `CORS_ORIGINS` | Prefer explicit origins instead of `*` in production |
| `OTEL_ENABLED` | Optional; install OTel packages first ([OBSERVABILITY.md](./OBSERVABILITY.md)) |
| SSO client ids | Optional ([SSO.md](./SSO.md)) |

After rotating `SECRET_KEY`, re-save workspace email config so IMAP/SMTP passwords re-encrypt.

Protocol stability: [PROTOCOL_SLA.md](./PROTOCOL_SLA.md).
