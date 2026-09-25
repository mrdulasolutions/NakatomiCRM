# Orchestrator interoperability (P6.5)

Nakatomi composes with **any** workforce controller using the same contract. Paperclip is the [reference guide](./PAPERCLIP.md); these patterns apply elsewhere.

## Contract (always)

1. One Nakatomi workspace per customer/environment.
2. **One scoped API key per autonomous worker** — see [AGENT-WORKFORCE-KEYS.md](../AGENT-WORKFORCE-KEYS.md).
3. Agents connect via **MCP** (`/mcp`) or **REST/OpenAPI**.
4. Nakatomi records **business state and attribution** — not assignment source or org chart.

## No orchestrator (solo agent)

Single Hermes, Claude Code, or Cursor session with one or more role-specific keys over time. Use `entity_context` for takeover between sessions. See [5-MINUTE-AGENT.md](../5-MINUTE-AGENT.md) and [AgentLab.md](../../AgentLab.md).

## Custom cron / scripts

Schedule `httpx` or CLI against REST compounds (`GET /agent/entity-context`, `GET /agent/activity`). No Paperclip required.

## OpenGateway / multi-agent rooms

Rooms can coordinate chat; Nakatomi remains the CRM spine. Mint per-agent keys for each participant that mutates CRM state.

## What Nakatomi does not implement

- Org chart, budgets, wake schedules, task assignment policy (orchestrator concerns).
- Tool Gateway policy (optional layer in front of `/mcp` — document in Paperclip guide only).

Strategy: [AGENT-OS.md](../AGENT-OS.md).
