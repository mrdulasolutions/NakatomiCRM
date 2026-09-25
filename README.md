# Nakatomi

**The open-source CRM built for AI agents.**

Nakatomi is an **agent-first, self-hostable CRM** designed to be operated by AI agents through **MCP, REST, A2A, and agent-native discovery**.

It is not a traditional CRM with an AI assistant bolted on.

**The agent is the primary user.**

Nakatomi provides the persistent, structured business state that agents need: people, companies, deals, relationships, activities, tasks, files, timelines, policies, approvals, and audit history.

You own the server.  
You own the database.  
You own the data.  
Your agents operate it.

**MIT licensed.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/mrdulasolutions/NakatomiCRM/actions/workflows/ci.yml/badge.svg)](https://github.com/mrdulasolutions/NakatomiCRM/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.0.8-blue.svg)](./CHANGELOG.md)
[![MCP](https://img.shields.io/badge/MCP-streamable_HTTP-111111)](./docs/MCP.md)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Self-Host](https://img.shields.io/badge/self--host-ready-2ea44f)](./docs/DEPLOY.md)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/nakatomicrm)

---

## Why Nakatomi?

Most CRMs were designed around a human sitting in a browser:

```text
Human
  │
  ▼
CRM UI
  │
  ▼
Database
```

AI gets added afterward:

```text
Human
  │
  ▼
CRM UI ─── AI Assistant
  │
  ▼
Database
```

Nakatomi starts from a different assumption:

```text
              ┌──────────────┐
              │   AI Agent   │
              └──────┬───────┘
                     │
              MCP / REST / A2A
                     │
              ┌──────▼───────┐
              │   Nakatomi   │
              │              │
              │ CRM + State  │
              │ + Policies   │
              │ + Timeline   │
              │ + Audit      │
              └──────┬───────┘
                     │
              ┌──────▼───────┐
              │   Postgres   │
              └──────────────┘
```

The CRM is the **persistent business state layer for your agents**.

An agent can:

- find or create a company
- find people associated with it
- maintain relationships
- create and manage opportunities
- move deals through pipelines
- log calls, meetings, and emails
- create tasks
- write notes
- inspect history
- ingest and normalize data
- query connected memory systems
- request human approval for sensitive actions
- react to webhooks
- operate with scoped permissions
- coordinate with other agents

The human does not have to be the one operating every record.

---

## What Nakatomi is

Nakatomi is the **structured system of record between your agents and your business**.

### Agents

Claude, ChatGPT, Cursor, Perplexity, custom agents, autonomous workers, and multi-agent systems.

### Protocols

- **MCP** — agent tools and interactive CRM operations
- **REST / OpenAPI** — universal API access
- **A2A** — agent discovery and task delegation
- **ACP context** — machine-readable workspace context
- **`llms.txt`** — LLM-oriented discovery

### Core

Contacts, companies, leads, deals, pipelines, products, quotes, activities, tasks, notes, relationships, files, timeline, audit history, policies, approvals, jobs, webhooks, custom fields, and custom objects.

### Infrastructure

PostgreSQL, FastAPI, SQLAlchemy, Alembic, Docker, local or S3-compatible file storage, optional OpenTelemetry, optional Google/GitHub SSO.

---

## Quickstart

### Docker

```bash
git clone https://github.com/mrdulasolutions/NakatomiCRM.git
cd NakatomiCRM

cp .env.example .env
# Set SECRET_KEY in .env

docker compose up -d

./install.sh --seed you@example.com
```

The installer creates your workspace and prints an API key.

Check that Nakatomi is running:

```bash
curl http://localhost:8000/health
```

You now have a running, self-hosted agent CRM.

### Python (local)

```bash
cp .env.example .env
docker run -d --name nk-pg -e POSTGRES_PASSWORD=nakatomi -e POSTGRES_USER=nakatomi \
  -e POSTGRES_DB=nakatomi -p 5432:5432 postgres:16
pip install -r requirements.txt
alembic upgrade head
python -m scripts.seed \
  --email you@example.com --password 'your-password-here' \
  --workspace-name "My Workspace" --workspace-slug mine
uvicorn app.main:app --reload
```

Fresh installs can also use the **branded welcome flow** at `/` to claim the instance in one step (workspace + owner + API key).

---

## Connect an AI agent

Nakatomi exposes an MCP server at:

```text
https://your-host/mcp
```

Authenticate with a workspace API key:

```text
Authorization: Bearer nk_your_key_here
```

Your agent can now operate the CRM through MCP.

For complete setup instructions: **[MCP Setup →](./docs/MCP.md)**

Configuration examples are included for Claude Desktop, Claude Code, Cursor, custom MCP clients, and local development.

Install agent skills from [docs/SKILLS.md](./docs/SKILLS.md) and [`.claude/skills/`](./.claude/skills/) (`nakatomi-crm`, `nakatomi-dashboard`).

---

## Example

Once connected, an agent can perform a workflow like:

> Find everyone at Acme Corp. Identify the people involved in the current opportunity. Add the missing decision maker, relate them to the company and deal, review the recent timeline, and create a follow-up task for next Tuesday.

The agent can execute that workflow through Nakatomi's structured primitives.

Nakatomi records the resulting state, relationships, timeline events, audit information, and task state.

The next agent sees the same business reality.

That's the point.

---

## MCP

Nakatomi's MCP server exposes CRM operations as agent-native tools.

Examples include:

```text
search_contacts
create_contact
update_contact

search_companies
create_company

create_lead
search_leads
convert_lead

list_pipelines
create_pipeline
create_deal
move_deal_stage

create_product
add_line_item
list_line_items
forecast

log_activity
add_note
create_task
list_tasks

relate
timeline

describe_schema
load_context
morning_briefing

memory_recall
memory_link
memory_trace

ingest
```

The MCP surface is intentionally kept **small, orthogonal, and stable**.

Agents should not need to understand hundreds of nearly-identical endpoints.

See **[docs/MCP.md](./docs/MCP.md)** for the complete tool reference.

---

## Agent-native by design

Nakatomi assumes that agents have imperfect memory, retry operations, discover systems dynamically, and sometimes make mistakes.

The API is designed accordingly.

### Idempotency

Automation can safely retry operations.

### Cursor pagination

Agents can traverse large datasets without relying on fragile offsets.

### Soft delete

Mistakes can be recovered from.

### Audit trail

Mutations record who or what performed them.

### Timeline

Agents can inspect what happened before acting.

### Relationships

Business context is represented as a graph rather than isolated records.

### Self-description

Agents can discover the schema instead of relying entirely on static documentation.

```text
/schema
/llms.txt
/.well-known/agent-card.json
/.well-known/agent.json
/discovery
```

### Agent-readable errors

Errors include actionable information whenever possible.

### Least privilege

API keys have capability scopes.

Agents don't automatically receive administrative privileges.

---

## Human-in-the-loop

Autonomous does not have to mean uncontrolled.

Nakatomi supports policies, scoped credentials, and approval workflows so an agent can operate independently while sensitive actions remain under human control.

For example:

```text
Agent
  │
  │ "Send this customer an email"
  ▼
Policy
  │
  ├── allowed → execute
  │
  └── requires approval
            │
            ▼
         Human
            │
       approve / reject
```

The goal is not to remove humans.

The goal is to let humans operate at the **decision layer instead of the data-entry layer**.

---

## Memory is deliberately separate

Nakatomi stores **structured truth**.

It does not try to become your universal semantic memory system.

Instead, Nakatomi provides a pluggable memory connector interface for systems such as DocDeploy, Supermemory, GBrain, and other compatible memory systems.

This creates a clean separation:

```text
Semantic memory
       │
       │
       ▼
    Agent
       │
       ▼
   Nakatomi
       │
       ▼
Structured business truth
```

Nakatomi knows:

> Alice works at Acme.  
> Acme has an open $75k opportunity.  
> Alice is the champion.  
> The opportunity moved to proposal yesterday.

Your memory system can know:

> Alice mentioned during a conversation that procurement has historically delayed similar purchases.

Both are useful.

They just aren't the same kind of data.

See **[docs/MEMORY.md](./docs/MEMORY.md)**.

Configure connectors via env (e.g. `MEMORY_CONNECTORS=docdeploy,supermemory`).

---

## Multi-agent ready

Nakatomi is designed to act as shared business state for multiple agents.

For example:

```text
                    Nakatomi
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   Sales Agent    Research Agent   Support Agent
        │              │              │
        ▼              ▼              ▼
      Leads         Accounts       Customers
```

Each agent can operate with its own credentials and permissions while sharing the same underlying business state.

A research agent can enrich a company. A sales agent can work the opportunity. A support agent can record customer activity.

They all see the same timeline.

---

## Data ownership

Nakatomi is designed to be self-hosted.

Your PostgreSQL database, files, API keys, workspace data, memory connections, and deployment remain under your control.

There is no required Nakatomi SaaS account.

There is no required phone-home analytics service.

A Nakatomi deployment is yours.

---

## What Nakatomi is not

Nakatomi deliberately does **not** try to become everything.

| Nakatomi is | Nakatomi is not |
| --- | --- |
| Agent-first CRM | A HubSpot clone |
| Structured business state | A universal semantic memory |
| REST + MCP + agent protocols | A proprietary AI interface |
| Self-hostable | SaaS lock-in |
| Composable | A giant all-in-one suite |
| Agent-operated | A traditional CRM UI |
| Human-supervised | Trust-every-agent-with-admin |

We intentionally do not build marketing automation suites, landing-page builders, forms platforms, full email clients, sequence engines, open-tracking systems, rich CRM UI as the primary product, or Zapier-style visual workflow builders.

Agents can compose those workflows using specialized tools and write the resulting structured state back to Nakatomi.

**We are the spine, not the soul.**

See [ETHOS.md](./ETHOS.md) and [ROADMAP.md](./ROADMAP.md).

---

## Architecture

```mermaid
%%{init: {"look": "handDrawn", "theme": "dark"}}%%
flowchart LR
    Agents[AI Agents] --> MCP[MCP]
    Agents --> REST[REST / OpenAPI]
    Agents --> A2A[A2A]
    Agents --> ACP[ACP Context]

    subgraph Nakatomi
        MCP
        REST
        A2A
        ACP
        Core[CRM Core]
        Events[Timeline / Audit / Webhooks]
    end

    MCP --> Core
    REST --> Core
    A2A --> Core
    ACP --> Core
    Core --> Events
    Core --> PG[(PostgreSQL)]
    Core --> Files[(Local / S3)]
    Core -.-> Memory[Memory Connectors]
```

See **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** for the deeper architecture and design decisions.

---

## Security model

Agents authenticate using workspace-scoped API keys.

Keys can be restricted by capability:

```text
contacts:read
contacts:write
deals:read
deals:write
email:send
admin:keys
...
```

Sensitive operations can require explicit permissions or human approval.

Nakatomi follows a **least-privilege** model rather than assuming every agent should have administrator access.

Humans can use JWT auth with `X-Workspace`; agents should prefer `nk_…` keys for MCP.

See **[SECURITY.md](./SECURITY.md)**.

---

## Deployment

Nakatomi runs anywhere you can run Docker and PostgreSQL.

### Railway

One-click deployment:

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/nakatomicrm)

Template variables, welcome flow, and post-deploy checklist: **[docs/RAILWAY_TEMPLATE.md](./docs/RAILWAY_TEMPLATE.md)**.

Before exposing production, run `python -m app check-config` with `ENVIRONMENT=production`.

### Other environments

Fly.io, Render, Kubernetes, a VPS, your own infrastructure, or local Docker.

See **[docs/DEPLOY.md](./docs/DEPLOY.md)** and **[docs/DEPLOYMENT_LESSONS.md](./docs/DEPLOYMENT_LESSONS.md)**.

---

## Development

Nakatomi uses Python 3.12, FastAPI, PostgreSQL, SQLAlchemy, Alembic, pytest, Ruff, and mypy.

Run the test suite:

```bash
export TEST_DATABASE_URL=postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi_test
export TEST_MIGRATE_URL=postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi_migrate

pytest -q
```

CI runs linting, type checking, tests, coverage, and migration smoke tests.

Operator CLI:

```bash
python -m app version
python -m app protocols
python -m app health --deep
python -m app check-config
```

Optional local audit UI: set `DASHBOARD_ENABLED=true` and open `/dashboard` (auto-enabled in development when unset).

---

## Documentation

| Document | What it covers |
| --- | --- |
| [Architecture](./docs/ARCHITECTURE.md) | System architecture and data flows |
| [MCP](./docs/MCP.md) | MCP setup and tool reference |
| [AgentLab](./AgentLab.md) | Agent deployment patterns and recipes |
| [Memory](./docs/MEMORY.md) | Memory connectors and cross-linking |
| [Deployment](./docs/DEPLOY.md) | Production deployment |
| [Railway template](./docs/RAILWAY_TEMPLATE.md) | One-click deploy configuration |
| [Protocol SLA](./docs/PROTOCOL_SLA.md) | REST/MCP/A2A/ACP contracts |
| [Observability](./docs/OBSERVABILITY.md) | OpenTelemetry |
| [SSO](./docs/SSO.md) | Google/GitHub authentication |
| [Skills](./docs/SKILLS.md) | Claude Code / agent skill install |
| [Roadmap](./ROADMAP.md) | What's next |
| [Ethos](./ETHOS.md) | Design principles |
| [Security](./SECURITY.md) | Security policy |
| [Changelog](./CHANGELOG.md) | Release history |

[Wiki](https://github.com/mrdulasolutions/NakatomiCRM/wiki) — deeper dives on subsystems.

---

## Contributing

Nakatomi is open source and welcomes contributions.

The project intentionally values simple primitives, stable agent interfaces, clear contracts, composability, self-hosting, data ownership, least privilege, and boring infrastructure.

Before proposing a large feature, read **[ETHOS.md](./ETHOS.md)**.

A feature that makes Nakatomi more capable while making the agent surface larger, less predictable, or more coupled to a particular vendor may not be an improvement.

See [CONTRIBUTORS.md](./CONTRIBUTORS.md), [AUTHORS.md](./AUTHORS.md), and [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

---

## License

Nakatomi is released under the **MIT License**.

See [LICENSE](./LICENSE).

---

## The idea

Nakatomi started from a simple premise:

**If AI agents are going to operate businesses, they need somewhere to keep the state of those businesses.**

Not another chatbot. Not another dashboard. Not another CRM with an AI button.

A shared, structured, open system of record that agents can actually operate.

That's Nakatomi.
