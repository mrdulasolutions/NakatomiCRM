# AgentLab recovery recipe (P3.3)

When an agent mis-writes CRM state, recover using Nakatomi forensics — not orchestrator logs.

## 1. Stop the agent

Revoke or rotate the misbehaving key (`POST /workspace/api-keys` revoke) so it cannot continue.

## 2. Inspect timeline + audit

```bash
curl -H "Authorization: Bearer $ADMIN_KEY" \
  "$HOST/agent/explain-change?entity_type=deal&entity_id=DEAL_ID"
```

Or MCP: `explain_change`, `search_audit`, `entity_as_of`.

## 3. Time-travel read

```bash
curl -H "Authorization: Bearer $KEY" \
  "$HOST/entities/deal/DEAL_ID/as-of?ts=2026-09-24T12:00:00Z"
```

## 4. Correct state

- Prefer **PATCH** with human-approved values
- Use **soft delete** unless hard delete is explicitly required
- Log an activity describing the correction

## 5. Webhook dead letters

If downstream automations failed:

```bash
curl -H "Authorization: Bearer $KEY" "$HOST/webhooks/dead-letters"
curl -X POST -H "Authorization: Bearer $KEY" "$HOST/webhooks/dead-letters/{id}/replay"
```

## 6. Handoff to another agent

`POST /agent/handoff` with summary + `entity_context` for the receiver.

See also [AgentLab.md](../AgentLab.md) handoff section.
