# Cloudflare edition parity (P4.4 stub)

Nakatomi core targets **self-hosted Postgres + Docker/Railway**. A Cloudflare Workers edition is **not shipped** in this repo.

| Capability | Core (this repo) | Cloudflare (future) |
| --- | --- | --- |
| REST + MCP | Yes | Would need Durable Objects or external DB |
| Postgres JSONB | Yes | Hyperdrive / external Postgres |
| Webhooks worker | In-process | Queue consumer |
| Files S3/local | Yes | R2 |
| Agent OS compounds | Yes | Same API surface target |

Track gaps here when a CF port is scoped; do not block core roadmap on CF parity.
