# Agent OS — business state for autonomous workforces

Nakatomi is not “a CRM with MCP.” It is the **business-state layer** that autonomous agents read and write while orchestrators and runtimes handle everything else.

## North star

> **Nakatomi is the business-state layer for autonomous workforces.**
>
> Orchestrators decide who works and when. Agent runtimes decide how to reason and act. Nakatomi maintains the structured, durable record of what the business knows and what happened.

> **Nakatomi should be useful with an orchestrator, without an orchestrator, or with several orchestrators at once.**

## Guardrail (read this before adding features)

> **Never make Nakatomi know how an agent got its assignment.** Make Nakatomi exceptionally good at knowing **what the agent did**, **what changed**, **why it changed**, **who did it**, and **what the next agent needs to know.**

That is the data plane. Org charts, budgets, wake schedules, and “who reports to whom” belong in orchestrators (Paperclip, custom controllers, cron, or nothing at all).

## Three layers

| Layer | Owns | Examples |
| --- | --- | --- |
| **Orchestration (optional)** | Who works, tasks, budgets, scheduling, permissions/policy | Paperclip, custom, **none** |
| **Agent runtimes** | Reasoning, skills, conversation memory, web/tools | Hermes, Claude Code, Codex, Grok, Cursor, OpenClaw, custom |
| **Nakatomi** | Entities, graph, pipeline, timeline, approvals, handoffs, **agent attribution** | MCP, REST, A2A, ACP |

```text
                 ORCHESTRATION (optional)
        ┌─────────────────────────────┐
        │ Paperclip / custom / none   │
        └──────────────┬──────────────┘
                       │
                 AGENT RUNTIMES
        ┌─────────────────────────────┐
        │ Hermes / Claude / Grok / …  │
        └──────────────┬──────────────┘
                       │
              MCP / REST / A2A
                       │
                       ▼
              ┌───────────────────┐
              │    NAKATOMI       │
              │ Business state    │
              │ Timeline          │
              │ Approvals         │
              │ Agent attribution │
              └───────────────────┘
```

**Two memories (do not merge them):**

- **Runtime memory** — preferences, reasoning context, “Matt follows up on Tuesdays.” See [MEMORY.md](./MEMORY.md) and [AgentLab.md](../AgentLab.md).
- **Nakatomi memory** — structured truth: “Acme has a $125k deal in Proposal.”

**Optional deployment topology (Nakatomi does not implement this):**

```text
Agent → Orchestrator Tool Gateway (allow / block / rate-limit / ask-human) → Nakatomi MCP → business state
```

Orchestrator answers: **Was this agent allowed to act?** Nakatomi answers: **What happened to the business?**

Workforce interoperability (Paperclip as first **reference**, not dependency): [integrations/PAPERCLIP.md](./integrations/PAPERCLIP.md).

---

## Protocol map

Use the right entry point for the job. Do not overload one tool for everything.

| Surface | When to use | Shipped today |
| --- | --- | --- |
| **`load_context`** (MCP) / **`GET /acp/context`** | Boot a session: schema hints, policies, open work, workspace shape | Yes — [ACP.md](./ACP.md) |
| **`morning_briefing`** (MCP) | Workspace-wide open work, stale deals, pending approvals | Yes |
| **`entity_context`** (MCP) / **`GET /agent/entity-context`** | **One entity’s** coherent bundle | Yes — [AGENT-WORKFORCE-KEYS.md](./AGENT-WORKFORCE-KEYS.md) |
| **`agent_activity`** / **`GET /agent/activity`** | Workforce facts from timeline | Yes |
| **A2A tasks** | Delegate work to another agent; link to CRM tasks and HITL | Yes — [A2A.md](./A2A.md) |
| **REST / OpenAPI** | Scripts, Grok surfaces without MCP, parity with MCP | Yes — always the escape hatch — [MCP_PARITY.md](./MCP_PARITY.md) |

**Session boot (today):** `describe_schema` or `load_context` → work → `morning_briefing` when you need open-work rollup.

**Account takeover (future flagship):** fresh runtime session → **`entity_context("company", "Acme")`** → continue without chat history.

---

## Eight capability pillars

Each pillar: what exists today, what **P5** adds, and what we refuse to build.

### 1. Entity-scoped business state (`entity_context`)

**Today:** Agents compose state from many calls — `search_companies`, neighbors via REST, `timeline`, `upsert_account_map`, etc.

**Next (P5.1):** Single compound:

```text
entity_context(entity_type, entity_id_or_slug)
```

Returns a coherent bundle for that entity (people, deals, relationships, recent timeline, open tasks, pending approvals — bounded and versioned).

**Non-goals:** Re-implement orchestrator task lists; duplicate runtime RAG; unbounded dumps that blow context windows.

### 2. Extraordinary timeline (attribution)

**Today:** Append-only `TimelineEvent` with `actor_api_key_id` on mutations.

**Next (P5.2):** Resolved **`actor_label`** on timeline reads (e.g. “Research Agent”, not `nk_7f3…`). Optional `since` filters for workforce reviews.

**Non-goals:** Replacing orchestrator run logs; storing assignment reason on each event.

### 3. Agent identity (workforce roster)

**Today:** Per-worker **`ApiKey`**: `name`, `scopes`, optional `data` JSONB; timeline ties to key id.

**Next (P5.3):** Documented **Agent Identity** model:

```text
Agent Identity (Nakatomi)
├── stable Nakatomi agent id (key id)
├── display name
├── role
├── capabilities
├── status
├── credentials / scopes
└── external_identities (map)
     ├── paperclip_agent_id
     ├── hermes_agent_id
     └── …
```

External IDs are **references**, not primary keys. Nakatomi does not depend on Paperclip’s agent schema.

**Non-goals:** Org chart, budgets, or reporting lines in core CRM tables.

### 4. Handoffs between agents

**Today:** [A2A tasks](./A2A.md) with `context_url`, CRM tasks, approvals.

**Next (P5.4):** Documented handoff payload + AgentLab recipe (“AE Agent, take over Acme”) aligned with `entity_context`.

**Non-goals:** Built-in workflow engine; visual swarm designer.

### 5. Explainability (`explain_change`)

**Today:** Row audit diffs, forensics (`entity_as_of`, search audit), approval chains.

**Next (P5.5):** Compound **`explain_change`** for material transitions (e.g. stage moves) with evidence pointers.

**Non-goals:** LLM-generated excuses stored as truth; hiding audit behind narrative-only fields.

### 6. Workforce activity (`agent_activity`)

**Today:** `morning_briefing` for workspace open work; timeline as raw facts.

**Next (P5.6):** Structured query:

```text
agent_activity(since, agent_id?, entity_type?, activity_type?)
```

Example shape (aggregates backed by DB):

```json
{
  "agent": "research-agent",
  "companies_enriched": 37,
  "contacts_created": 81,
  "opportunities_touched": 9,
  "activities_logged": 112,
  "approvals_pending": 3
}
```

**Non-goals:** “AI workforce analytics” product; second orchestration UI; storing **why** work was scheduled.

### 7. Human-in-the-loop

**Today:** `ApprovalRequest`, workspace policies, MCP `propose_action` / `decide_approval`, timeline events.

**Next:** Tie workforce demos and `entity_context` to pending approvals on the entity bundle.

**Non-goals:** Replacing orchestrator “ask human” gateways — compose them in deployment topology instead.

### 8. Composable protocols (MCP + REST + A2A + ACP)

**Today:** Curated MCP tools, A2A task runtime, ACP context pack, OpenAPI parity target.

**Next (P6):** Workforce interoperability docs — per-agent keys, scope templates, reference orchestrator setup — without Nakatomi “plugins” per vendor.

**Non-goals:** MCP-only features; one MCP tool per REST route; “Paperclip support” as a special case in code.

---

## P5 implementation priority (when coding starts)

| Order | Item | Why |
| --- | --- | --- |
| 1 | **P5.1** `entity_context` + **P5.2** actor labels | Defines the data plane; unlocks takeover demo |
| 2 | **P5.3** Agent Identity conventions | Readable timeline + “who owns Acme?” |
| 3 | **P5.6** `agent_activity` | Facts for humans, dashboards, orchestrators |
| 4 | **P5.4** handoffs + **P5.5** `explain_change` | Multi-agent continuity and trust |
| 5 | **P5.7** demo scripts | Prove abstraction in AgentLab / 5-minute path |

Track items in [ROADMAP.md](../ROADMAP.md) **P5** and **P6**.

---

## Explicit non-goals

- Nakatomi as **orchestrator replacement** (no org chart, budgets, wake scheduler, assignment source in core).
- Nakatomi as **runtime memory** replacement (vector prefs live in connectors — [MEMORY.md](./MEMORY.md)).
- **`agent_activity` as workforce analytics / orchestration dashboard.**
- **MCP-only** product — REST/OpenAPI remains parity ([MCP_PARITY.md](./MCP_PARITY.md)).
- Rich CRM UI, marketing suite, deep email client ([ETHOS.md](../ETHOS.md)).
- Framing contributions as “add Paperclip support” — prefer **workforce interoperability**.

---

## Where to go next

| You are… | Start here |
| --- | --- |
| First agent on Nakatomi | [5-MINUTE-AGENT.md](./5-MINUTE-AGENT.md) |
| Production GTM recipes | [AgentLab.md](../AgentLab.md) |
| Paperclip reference workforce | [integrations/PAPERCLIP.md](./integrations/PAPERCLIP.md) |
| Per-agent keys & scopes | [AGENT-WORKFORCE-KEYS.md](./AGENT-WORKFORCE-KEYS.md) |
| Protocol details | [MCP.md](./MCP.md), [A2A.md](./A2A.md), [ACP.md](./ACP.md) |
