# Memory connectors

Nakatomi stores structured CRM records and links them to memories held by
external providers. A `MemoryLink` connects a CRM entity to a connector name
and an external record ID. Link, list, and trace operations work with no
provider credentials configured.

Enabled connectors can receive event summaries from supported CRM write
paths and answer recall requests. Mirroring is best effort. An empty recall
result can also mean a connector failed or was unavailable.

Keep external connectors disabled on shared installations until you have
verified workspace isolation. Use dedicated provider credentials for each
isolated installation. Enable outbound sharing only after reviewing the
CRM data your provider will receive.

## Configure

`.env` (or Railway variables):

```
MEMORY_CONNECTORS=docdeploy,supermemory,gbrain

DOCDEPLOY_API_KEY=...
DOCDEPLOY_BASE_URL=https://x402.docdeploy.io

SUPERMEMORY_API_KEY=...
SUPERMEMORY_BASE_URL=https://api.supermemory.ai

# GBrain — expects a remote streamable-HTTP MCP endpoint (e.g. `gbrain serve`
# behind an ngrok tunnel, per https://github.com/garrytan/gbrain/blob/master/docs/mcp/DEPLOY.md).
# GBRAIN_TOKEN is minted with `bun run src/commands/auth.ts create <label>`.
GBRAIN_MCP_URL=https://your-brain.example.com/mcp
GBRAIN_TOKEN=...
```

Leave `MEMORY_CONNECTORS` empty to disable provider recall and mirroring. Existing links remain available.

## API

### `POST /memory/recall`

Query the selected enabled connectors and return merged results. The REST endpoint currently requires `memory:write`. The MCP `memory_recall` tool requires `memory:read`.

```json
POST /memory/recall
{
  "query": "what have we promised Acme about delivery timelines?",
  "entity_type": "company",
  "entity_id": "<uuid>",
  "limit": 10,
  "connectors": ["docdeploy", "supermemory"]
}
```

Response:

```json
{
  "items": [
    {
      "connector": "docdeploy",
      "external_id": "mem_abc123",
      "text": "…",
      "score": 0.81,
      "metadata": {...},
      "crm_links": ["company:uuid", "deal:uuid"]
    }
  ]
}
```

### `POST /memory/link`

Explicitly cross-link a CRM entity with an external memory.

```json
POST /memory/link
{
  "connector": "docdeploy",
  "external_id": "mem_abc123",
  "crm_entity_type": "contact",
  "crm_entity_id": "<uuid>",
  "note": "initial discovery call transcript"
}
```

### `POST /memory/webhook/{connector}`

The endpoint accepts authenticated connector events and can create links for
CRM references. Signature verification depends on the adapter. Keep inbound
delivery private unless your adapter enforces provider signatures.

## Export and restore

Workspace exports preserve the link rows and external IDs. Provider-side
memory content stays with the provider. Reconnect a compatible provider in
the destination installation and verify that it can resolve the same IDs
before relying on recall.

## Writing a new adapter

1. Create `app/services/memory/adapters/<name>.py`
2. Subclass `MemoryConnector` from `app.services.memory.base`
3. Implement workspace-scoped `store_event` and `recall`. Implement `verify_webhook` before enabling inbound delivery.
4. Register the adapter in `app.services.memory.registry._builtins()`
5. Document the env vars in `.env.example` and in this file

See the `DocDeployConnector` and `SupermemoryConnector` implementations for a
reference — both are ~100 lines of straightforward HTTP.

## Adapters

| Adapter | Status | Notes |
| --- | --- | --- |
| `docdeploy` | shipped | x402 pay-per-call memory. REST client via httpx. See https://www.docdeploy.io. |
| `supermemory` | shipped | REST API (`/v3/memories`, `/v3/search`) via httpx. See https://supermemory.ai. |
| `gbrain` | shipped | MCP-first self-wiring brain. Speaks streamable-HTTP MCP to `${GBRAIN_MCP_URL}` with a fresh session per call; uses `put_page` (markdown + YAML frontmatter) and `query` (hybrid search). See https://github.com/garrytan/gbrain. |
| `memcastle` | planned | API shape not yet documented. |

The three shipped adapters make real outbound calls but the request/response
shapes follow public docs at time of writing. DocDeploy and Supermemory may
evolve their APIs; GBrain's MCP tool surface is pinned to the upstream
`operations.ts` (stable tool names since v0.7).

## Conflict policy

Inbound connector events can create link rows and timeline events. CRM field updates remain explicit operations.
