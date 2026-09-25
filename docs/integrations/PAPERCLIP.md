# Workforce interoperability — Paperclip reference

This guide is **[P6.1](../AGENT-OS.md)** in the roadmap: how an **orchestrator + agent runtimes** compose with Nakatomi. **Paperclip is the reference implementation**, not a dependency. The same patterns work with Hermes alone, Claude Code, Cursor, custom cron, or **no orchestrator**.

Official Paperclip docs (external):

- [Hire your first agent](https://docs.paperclip.ing/guides/getting-started/your-first-agent/)
- [Add an MCP server to an agent](https://docs.paperclip.ing/how-to/add-mcp-server-to-agent/)
- [Tool Gateway API](https://docs.paperclip.ing/reference/api/tool-gateway/)
- [Agents API](https://docs.paperclip.ing/reference/api/agents/)
- [Adapters overview](https://docs.paperclip.ing/reference/adapters/overview/) (Claude Code, Codex, Gemini, Cursor, Hermes, Grok Local, …)

---

## Architecture

```text
                    ┌──────────────────────┐
                    │  ORCHESTRATOR        │
                    │  (example: Paperclip)│
                    │  org / tasks / budget│
                    │  Tool Gateway policy │
                    └──────────┬───────────┘
                               │ hires / assigns / wakes
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
     Research Agent        SDR Agent           AE Agent
     (any adapter)         (any adapter)       (any adapter)
          │                    │                    │
          │ MCP or REST        │                    │
          └────────────────────┼────────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │       NAKATOMI       │
                    │  per-agent API keys  │
                    │  timeline + state    │
                    └──────────────────────┘
```

**Separation:**

| Question | Who answers |
| --- | --- |
| Who should work? What’s the budget? May this tool call proceed? | Orchestrator (Paperclip Tool Gateway: allow / block / rate-limit / ask-human) |
| What do we know about Acme? What changed? Who did it? | Nakatomi |

Nakatomi does **not** implement the Tool Gateway. Document it only as an optional layer in front of `/mcp`.

---

## v0 integration (no Nakatomi plugin)

1. Deploy Nakatomi ([5-MINUTE-AGENT.md](../5-MINUTE-AGENT.md) or [DEPLOY.md](../DEPLOY.md)).
2. Mint **one API key per autonomous worker** — never one shared key for the whole workforce.
3. In Paperclip (or your orchestrator), attach **Nakatomi MCP per agent** with that agent’s Bearer token.
4. Use least-privilege scopes per role (below).
5. Rely on Nakatomi **timeline** (+ future **P5.2** actor labels) as institutional memory.

Naming convention (examples only):

```text
research-agent
sdr-agent
ae-agent
```

You may prefix with `paperclip-` for operator clarity; Nakatomi only sees key `name` and scopes.

### MCP endpoint

```text
https://YOUR_HOST/mcp
Authorization: Bearer nk_…
```

Parity rule: if a runtime lacks MCP, use OpenAPI + the same key — [MCP.md](../MCP.md), [MCP_PARITY.md](../MCP_PARITY.md).

### Example: Hermes-style MCP config (one adapter)

Paperclip documents MCP on agents; Hermes is one adapter, not the only path:

```yaml
mcp_servers:
  nakatomi:
    url: https://crm.example.com/mcp
    headers:
      Authorization: Bearer nk_research_agent_key_here
```

Repeat with **different keys** for SDR and AE agents.

### Optional: Tool Gateway in front of Nakatomi

```text
Agent → Paperclip Tool Gateway → Nakatomi MCP → Postgres
```

Use when policy must gate `send_email`, exports, or high-risk mutators before they hit Nakatomi. Nakatomi still records **business outcome** after allowed calls succeed.

---

## Per-agent scope matrix (starting point)

Adjust for your policies. Wildcard `*` is for dev only.

| Role | Typical scopes | Nakatomi work |
| --- | --- | --- |
| **Research** | `companies:read`, `companies:write`, `contacts:read`, `contacts:write`, `relationships:write`, `activities:write`, `notes:write` | Create/enrich accounts, log research activities |
| **SDR** | Research + `leads:write`, `tasks:write`, `email:send` (if sending — prefer HITL) | Prospecting, touches, qualification signals |
| **AE** | `deals:read`, `deals:write`, `quotes:write`, `contacts:read`, `activities:write`, `approvals:read` | Opportunities, proposals, stage moves |
| **Customer success** | `deals:read`, `contacts:read`, `contacts:write`, `activities:write`, `tasks:write` | Post-sale account work |

Mint keys via dashboard welcome flow, `POST /workspace/api-keys` (JWT), or seed scripts. Scope templates: [AGENT-WORKFORCE-KEYS.md](../AGENT-WORKFORCE-KEYS.md).

### External identities (P5.3 — optional metadata today)

Store orchestrator ids in `ApiKey.data` without coupling schema to Paperclip:

```json
{
  "agent_role": "research",
  "external_identities": {
    "paperclip_agent_id": "abc123",
    "paperclip_role": "Researcher"
  }
}
```

Nakatomi timeline should eventually show **Research Agent**, not raw key prefixes (**P5.2**).

---

## Flagship demo script (prove the abstraction)

**Goal:** Multiple agents + shared Nakatomi → durable state → **cold takeover** via `entity_context` (when **P5.1** ships; until then, compose with `timeline` + entity GETs as in [5-MINUTE-AGENT.md](../5-MINUTE-AGENT.md)).

### Setup

```text
CEO (Paperclip)
 ├── Research Agent   → nk_… research scopes
 ├── SDR Agent          → nk_… sdr scopes
 └── AE Agent           → nk_… ae scopes
```

CEO instruction (example):

```text
Build qualified pipeline from companies matching our ICP. Divide work among the team.
Do not hard-code a workflow in Nakatomi — use CRM tools and log everything to the timeline.
```

### What to star in Nakatomi (not Paperclip)

After a run, a human or script should be able to read **structured state**:

```text
NAKATOMI SNAPSHOT (example)

Companies discovered:       47
Contacts enriched:          83
Qualified opportunities:    11
Pipeline created:           $127,000
Human approvals pending:    3
Agents active:              3

Timeline (attributed — P5.2)
────────────────────────────────────────────
Research Agent → Acme enriched
Research Agent → Acme decision maker identified
SDR Agent      → Jane Doe added
SDR Agent      → Jane Doe contacted
AE Agent       → Acme opportunity created
AE Agent       → Opportunity moved to Discovery
Human          → Outreach approved
```

Paperclip separately shows tasks, runs, and budgets — that is **execution state**, not business state.

### Killer beat: takeover

1. Stop all agents (or end Paperclip runs).
2. Start a **new** AE session with no prior chat.
3. Prompt: **“Take over Acme Corp. Continue the deal.”**
4. Agent calls **`entity_context(company, Acme)`** (or today: `timeline` + searches).
5. Success = AE continues with full institutional context.

That demonstrates **Nakatomi as business-state layer**, not “Hermes integration.”

---

## Multi-runtime note

Paperclip adapters include Claude Code, Codex, Gemini, OpenCode, Cursor, Pi, Hermes, Grok Local, and others. Each can point at the same Nakatomi host with **different keys per role**. Nakatomi stays orchestrator- and runtime-agnostic.

---

## Other orchestrators (P6.5)

Same contract:

- One Nakatomi workspace per customer/environment.
- One scoped key per worker identity.
- MCP preferred; REST when needed.
- No assignment metadata required in Nakatomi.

Examples to document later: custom cron agents, OpenGateway rooms, solo Claude Code without Paperclip ([AgentLab.md](../../AgentLab.md)).

---

## Related reading

- [AGENT-OS.md](../AGENT-OS.md) — north star, guardrails, P5 pillars
- [AgentLab.md](../../AgentLab.md) — GTM recipes
- [A2A.md](../A2A.md) — delegate work between agents
- [ACP.md](../ACP.md) — `load_context` vs future `entity_context`
