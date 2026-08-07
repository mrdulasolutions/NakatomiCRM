# ACP — Agent Context Protocol (Nakatomi)

Nakatomi’s **Agent Context Protocol** is a product layer: a versioned,
machine-readable **context pack** that an agent (or A2A peer) loads once per
session so it stops inventing schema, policies, and open work.

This is **not** the same as IBM/BeeAI’s Agent Communication Protocol (which is
converging into A2A). We implement **context** here; **peer communication** is
A2A ([docs/A2A.md](./A2A.md)).

## Boot sequence (recommended)

```
1. GET /discovery          → find surfaces
2. GET /acp/context        → load pack (or MCP load_context)
3. Work with REST / MCP using scopes from pack.policies.scopes_on_this_key
4. MCP morning_briefing    → refresh open work mid-session
5. Idempotency-Key on writes
```

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/acp/context` | Full pack; auth required |
| `GET` | `/acp/context?sections=hints,policies` | Partial pack |
| MCP | `load_context` | Same payload |

### Caching

- Response includes `ETag: "<hash>"`
- Send `If-None-Match: "<hash>"` → **304** when unchanged

## Pack shape (`nakatomi.acp/v1`)

```json
{
  "protocol": "nakatomi.acp/v1",
  "workspace": { "id": "…", "slug": "…", "name": "…" },
  "generated_at": "…",
  "schema_version": "0.5.0",
  "entities": [ ],
  "custom_fields": [ ],
  "pipelines": [ ],
  "views": [ ],
  "view_presets": [ ],
  "policies": {
    "approvals": [ ],
    "scopes_on_this_key": ["*"],
    "role": "owner"
  },
  "open_work": {
    "tasks_due": [ ],
    "stale_deals": [ ],
    "pending_approvals": [ ],
    "failed_webhooks": [ ]
  },
  "event_types": [ ],
  "mcp": { "url": "/mcp", "tools": [ ] },
  "a2a": { "agent_card": "/.well-known/agent-card.json", "tasks_base": "/a2a/tasks" },
  "memory_connectors": [ ],
  "hints": [ ],
  "etag": "…"
}
```

## Rules for agents

1. **Do not invent field names** — use `entities` + `custom_fields`.
2. **Respect `policies.scopes_on_this_key`** — missing scopes → 403 with suggestion.
3. **Prefer compound MCP tools** after boot: `upsert_account_map`, `advance_deal`,
   `log_interaction`, `morning_briefing`.
4. **HITL**: if `policies.approvals` lists an action, use `propose_action` / A2A
   `require_approval=true` instead of direct write.
