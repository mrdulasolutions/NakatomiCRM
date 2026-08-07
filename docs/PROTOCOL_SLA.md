# Protocol stability SLA (v1.0)

Nakatomi exposes four agent surfaces. Each has an independent **contract
version** published on every discovery endpoint.

| Surface | Contract | Boot / discover |
| --- | --- | --- |
| **REST** | OpenAPI 3 + `/schema` entity manifest | `GET /openapi.json`, `GET /schema` |
| **MCP** | Streamable HTTP tools at `/mcp` | `GET /discovery` → `links.mcp` |
| **A2A** | Agent card + REST tasks | `/.well-known/agent-card.json`, `/a2a/tasks` |
| **ACP** | Versioned context packs | `GET /acp/context` |

At v1.0 ship, all four contracts are **`1.0`** and the app is marked
**`stability: stable`**.

## Machine-readable source of truth

```http
GET /schema
GET /discovery
GET /health
```

Response fields (names may appear nested under `protocols` on
`/discovery`):

| Field | Meaning |
| --- | --- |
| `protocols` / `versions` | `{rest, mcp, a2a, acp}` → contract version |
| `stability` | `stable` (post-1.0) |
| `sunset_notice_days` | Minimum notice before a break (default **90**) |
| `scheduled_sunsets` | List of announced removals with `remove_after` dates |
| `protocol_policy` | Human-readable policy string |

CLI:

```bash
python -m app protocols
python -m app version
```

## What counts as breaking

**Breaking** (requires major SemVer + sunset entry):

- Removing or renaming an MCP tool, required parameter, or documented
  return field used by agents
- Changing A2A task lifecycle state names or required card fields
- Removing an ACP context pack section without a replacement path
- Changing auth header schemes or API key prefix semantics
- Removing a REST route that appears in `/schema` endpoints maps

**Non-breaking** (minor/patch, no sunset):

- Adding optional fields, tools, routes, or event types
- Expanding enums with new values agents can ignore
- Performance, logging, and internal refactors
- New optional env flags (OTel, SSO, …)

## Sunset process

1. Announce in `CHANGELOG.md` under a **Deprecations** heading with the
   target `remove_after` date (≥ 90 days out).
2. Append an object to `SCHEDULED_SUNSETS` in `app/protocol.py` so agents
   see it on `/schema` and `/discovery`.
3. Bump Nakatomi major version when the removal ships; bump the affected
   protocol contract version in `PROTOCOL_VERSIONS`.

## Compatibility commitment

- **1.x** remains compatible within the contract versions advertised at
  release. Agents should pin on protocol contract versions, not only app
  SemVer.
- Security fixes may land as patch releases without notice beyond the
  usual advisory.
- Pre-1.0 (`0.x`) had no SLA; this document applies from **1.0.0** onward.
