# A2A — Agent2Agent on Nakatomi

Nakatomi implements a **REST binding** of the Agent2Agent protocol surface
(discovery + tasks). We chose REST over JSON-RPC so tasks share API keys,
OpenAPI, scopes, and webhooks with the rest of the CRM.

## Discovery

| URL | Purpose |
| --- | --- |
| `GET /.well-known/agent-card.json` | Spec-preferred Agent Card (dynamic) |
| `GET /.well-known/agent.json` | Legacy path — same payload |
| `GET /a2a/agent-card` | Convenience under `/a2a` |
| `GET /discovery` | Full surface index including card preview |

Cards inject the request base URL (works on Railway / localhost without rewrite).
With a Bearer token, the card includes `nakatomi.extended` MCP tool hints.

## Task lifecycle

```
submitted → working → input_required → working → completed
                   ↘ failed
                   ↘ canceled
```

| Method | Path | Scope |
| --- | --- | --- |
| `POST` | `/a2a/tasks` | `a2a:invoke` |
| `GET` | `/a2a/tasks` | `a2a:invoke` |
| `GET` | `/a2a/tasks/{id}` | `a2a:invoke` |
| `POST` | `/a2a/tasks/{id}/messages` | `a2a:invoke` |
| `POST` | `/a2a/tasks/{id}/complete` | `a2a:invoke` |
| `POST` | `/a2a/tasks/{id}/fail` | `a2a:invoke` |
| `POST` | `/a2a/tasks/{id}/cancel` | `a2a:invoke` |
| `POST` | `/a2a/tasks/{id}/input-required` | `a2a:invoke` |

### Create body

```json
{
  "title": "Enrich Acme",
  "skill": "contact-hygiene",
  "input": { "domain": "acme.com" },
  "entity_type": "company",
  "entity_id": "…",
  "context_etag": "from ACP pack",
  "require_approval": false,
  "create_crm_task": false,
  "callback_url": null
}
```

- `require_approval: true` → status `input_required` + linked `ApprovalRequest`
- Approving the linked approval resumes the A2A task to `working`
- Rejecting fails the A2A task
- Every task response includes `context_url: "/acp/context"` for handoffs

## Mapping

| A2A | Nakatomi |
| --- | --- |
| Agent Card | Dynamic `build_agent_card` |
| Task | `a2a_tasks` row |
| Message | `messages` JSONB on the task |
| Artifact | `artifacts` JSONB (optional file_id later) |
| HITL | `ApprovalRequest` via `linked_approval_id` |
| Human work | optional CRM `Task` via `create_crm_task` |

## Events

- `a2a.task.created`
- `a2a.task.updated` (message, complete, fail, cancel, approval resume)

Subscribe with workspace webhooks as usual.

## Multi-agent patterns

See [AgentLab.md](../AgentLab.md) for recipes. Short form:

1. **Control plane** mints scoped keys (`contacts:write` only) and posts A2A tasks.
2. **Specialist** agents pull `GET /a2a/tasks?status=working`, do work, `complete`.
3. **Compliance auditor** never receives `*:delete` or `email:send`.
4. **Handoff**: include `context_etag` from ACP so the peer can revalidate context.
