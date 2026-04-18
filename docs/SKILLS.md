# Installing Nakatomi as an agent skill

Nakatomi is most useful when your agents know how to *use* it without you
repeating yourself. This file covers three installation modes.

## 1. Claude Code (local CLI / IDE)

Nakatomi ships two skills under `.claude/skills/`:

- **`nakatomi-crm`** — teaches the agent the core operating rules: prefer
  `external_id` for upserts, call `describe_schema` first, use `timeline`
  before acting on an entity, use `relate` to enrich the graph.
- **`nakatomi-dashboard`** — triggers on "nakatomi dashboard" and spins up the
  local stack + opens Chrome to the audit dashboard.

To install into your user profile so every Claude Code project sees them:

```bash
mkdir -p ~/.claude/skills
cp -R .claude/skills/nakatomi-crm ~/.claude/skills/
cp -R .claude/skills/nakatomi-dashboard ~/.claude/skills/
```

Or leave them scoped to this repo — Claude Code auto-discovers them from
`.claude/skills/` in the working directory.

## 2. Claude Agent SDK (programmatic)

The Claude Agent SDK can load skills from a directory. Point it at
`.claude/skills/` or reference the skill frontmatter directly in your system
prompt.

```python
from anthropic import Anthropic

client = Anthropic()
# See Anthropic SDK docs for current skill loading API
```

The essential content of the `nakatomi-crm` skill is a ~200-line SKILL.md
file with a strong trigger description and a checklist. Re-read it verbatim
in your own agents if you're not on Claude Code.

## 3. OpenAI / ChatGPT, Perplexity, other agent hosts

These hosts don't have Claude's skill system, but they do support MCP
servers. Point them at `/mcp` with the bearer header. The MCP
`describe_schema` tool is the entry point — once an agent calls it, the full
shape of Nakatomi is in context for the rest of the session.

For ChatGPT Custom GPTs, you can also import `/openapi.json` as an Action.

## Skill anatomy

A Claude Code skill is a directory with a `SKILL.md` file. The first lines are
YAML frontmatter:

```yaml
---
name: nakatomi-crm
description: Triggers when the user references Nakatomi CRM operations...
---
```

The body is the "if this trigger fires, do this" instructions. Keep it
<200 lines; longer skills dilute triggering accuracy.

## Keeping skills in sync

When you change the REST API or MCP surface, update:

1. `docs/MCP.md` (human-facing)
2. `llms.txt` (LLM-facing summary)
3. `public/.well-known/agent.json` (A2A capabilities)
4. `.claude/skills/nakatomi-crm/SKILL.md` (instructions)
5. The `/schema` manifest helper in `app/routers/schema.py`

CI should fail if any of those drift. Adding a drift-check script is on the
[roadmap](../ROADMAP.md#v11--repo-hygiene--agent-surface-in-progress).
