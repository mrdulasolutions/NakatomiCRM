# Workforce interoperability demo (P5.7 / P6.4)

Scripted demo: **multi-agent workforce → Nakatomi → cold takeover** via `entity_context`. Orchestrator optional ([Paperclip reference](../integrations/PAPERCLIP.md)).

## Prerequisites

- Nakatomi deployed (`PUBLIC_BASE_URL` set)
- Three API keys: `research-agent`, `sdr-agent`, `ae-agent` ([AGENT-WORKFORCE-KEYS.md](../AGENT-WORKFORCE-KEYS.md))
- MCP client per agent (Hermes, Claude Code, Cursor, etc.)

## Act 1 — Research

As **Research Agent** (research scopes):

1. `load_context` or `describe_schema`
2. Create/enrich target accounts (e.g. ICP list)
3. `log_activity` / notes on companies

## Act 2 — SDR

As **SDR Agent**:

1. `entity_context(company, "<name>")` on assigned accounts
2. Add contacts, log touches, qualify signals

## Act 3 — AE

As **AE Agent**:

1. Create/move deals, `propose_action` if HITL required
2. Ensure timeline shows attributed `actor_label` per key name / `display_name`

## Snapshot (human or script)

```bash
export HOST="$PUBLIC_BASE_URL"
export SINCE=$(date -u -v-1d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ)
curl -s -H "Authorization: Bearer $AE_KEY" \
  "$HOST/agent/activity?since=$SINCE" | jq .
```

## Act 4 — Killer beat (takeover)

1. Stop all agent sessions.
2. Start **new** AE session (empty chat).
3. Prompt: *“Take over Acme Corp and continue the deal.”*
4. Tool: `entity_context("company", "Acme Corp")` or `GET /agent/entity-context?entity_type=company&entity_ref=Acme%20Corp`

Success = full bundle (entity, contacts, deals, timeline with labels, tasks, approvals) without prior conversation.

## Optional orchestrator layer

Configure Paperclip agents with per-key MCP to `$HOST/mcp`. CEO goal example: *“Build qualified pipeline from our ICP.”* Nakatomi remains source of truth for numbers in Act 3 snapshot.
