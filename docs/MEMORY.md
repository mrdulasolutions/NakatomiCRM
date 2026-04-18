# Memory connectors

Nakatomi does not implement semantic memory. Agents already have good memory
systems. Instead, Nakatomi offers a small bidirectional bridge:

- **Outbound:** on every CRM mutation, Nakatomi can mirror a summary to each
  configured memory connector.
- **Inbound:** memory systems can POST to `/memory/webhook/{connector}` with a
  signed payload; Nakatomi decodes it, finds the referenced CRM entity via
  `MemoryLink`, and optionally triggers a CRM update.
- **Cross-link:** every memory write returns a `MemoryLink` row that maps
  `(crm_entity_type, crm_entity_id)` ↔ `(connector, external_id)`. Retrieving
  a CRM entity can surface linked memories; recalling a memory can surface
  linked CRM entities.

## Configure

`.env` (or Railway variables):

```
MEMORY_CONNECTORS=docdeploy,supermemory,gbrain

DOCDEPLOY_API_KEY=...
DOCDEPLOY_BASE_URL=https://x402.docdeploy.io

SUPERMEMORY_API_KEY=...
SUPERMEMORY_BASE_URL=https://api.supermemory.ai

# GBrain — expects a running GBrain MCP server (stdio or HTTP).
# Point this at the HTTP MCP URL you deploy per the GBrain docs.
GBRAIN_MCP_URL=https://your-brain.example.com/mcp
GBRAIN_TOKEN=...
```

Leave `MEMORY_CONNECTORS` empty to disable entirely. When disabled, all
`/memory/*` endpoints still work but return empty results.

## API

### `POST /memory/recall`

Fan out a query across all enabled connectors, return merged results.

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

Inbound webhook from a memory system. Each connector has its own payload
format; the adapter is responsible for verifying the signature, extracting
the relevant memory id and any CRM references, writing a `MemoryLink`, and
optionally mutating the CRM.

## Writing a new adapter

1. Create `app/services/memory_adapters/<name>.py`
2. Subclass `MemoryConnector` from `app.services.memory.base`
3. Implement `store_event`, `recall`, and (optionally) `verify_webhook`
4. Register the adapter in `app.services.memory.registry._BUILTINS`
5. Document the env vars in `.env.example` and in this file

See the `DocDeployConnector` and `SupermemoryConnector` implementations for a
reference — both are ~100 lines of straightforward HTTP.

## Adapters

| Adapter | Status | Notes |
| --- | --- | --- |
| `docdeploy` | stub | x402 pay-per-call memory. See https://www.docdeploy.io. |
| `supermemory` | stub | REST API. See https://supermemory.ai. |
| `gbrain` | stub | MCP-first self-wiring brain. See https://github.com/garrytan/gbrain. Adapter talks to the remote MCP endpoint. |
| `memcastle` | planned | API shape not yet documented. |

The stubs make real HTTP calls but the request/response shapes are based on
public docs at time of writing. You will likely need to adjust them for your
account's exact API version.

## Conflict policy

Currently: **inbound memory writes never overwrite CRM fields.** They can
append to `data` and create timeline events. A future `conflict_policy`
config will allow opt-in overwrite rules.
