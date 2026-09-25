# Agent workforce API keys (P6.2)

Per-agent keys for autonomous workforces. See [AGENT-OS.md](./AGENT-OS.md) and [integrations/PAPERCLIP.md](./integrations/PAPERCLIP.md).

## Rules

1. **One key per worker identity** — never share one `nk_…` across Research, SDR, and AE.
2. Set **`ApiKey.name`** to a stable id (`research-agent`, `sdr-agent`, …).
3. Optional **`ApiKey.data`** JSON:

```json
{
  "display_name": "Research Agent",
  "agent_role": "research",
  "external_identities": {
    "paperclip_agent_id": "abc123"
  }
}
```

4. Mint keys with `POST /workspace/api-keys` (JWT) or the welcome flow; assign scopes below.

## Scope templates (starting point)

Adjust for your policies. Use `*` only in dev.

| Role | Scopes |
| --- | --- |
| **Research** | `companies:read`, `companies:write`, `contacts:read`, `contacts:write`, `relationships:write`, `activities:write`, `notes:write`, `timeline:read` |
| **SDR** | Research scopes + `leads:write`, `tasks:write`, `email:send` (prefer HITL via `propose_action`) |
| **AE** | `deals:read`, `deals:write`, `quotes:write`, `contacts:read`, `activities:write`, `approvals:read`, `timeline:read`, `companies:read` |
| **Read-only overseer** | `*:read`, `timeline:read`, `approvals:read` |

All roles need **`timeline:read`** for `entity_context`, `agent_activity`, and attributed timeline.

## REST compounds (P5)

| Endpoint | Purpose |
| --- | --- |
| `GET /agent/entity-context?entity_type=company&entity_ref=Acme` | Business-state bundle |
| `GET /agent/activity?since=2026-01-01T00:00:00Z` | Workforce facts |
| `GET /agent/agents` | Roster |
| `GET /agent/explain-change?entity_type=company&entity_id=…` | Evidence chain |
| `POST /agent/handoff` | Handoff payload + embedded `entity_context` |

MCP: `entity_context`, `agent_activity`, `list_agents`, `explain_change`.
