# MCP (Model Context Protocol) usage

Nakatomi exposes an MCP server at `/mcp` using streamable HTTP transport.

**Two auth modes, pick the one your client supports:**

- **OAuth 2.1** — what Claude Desktop's "Add Custom Connector" GUI and
  ChatGPT's Custom Connectors do. The client discovers our auth server via
  `/.well-known/oauth-authorization-server`, runs the PKCE authorization-code
  flow in the browser, and gets back an access token + refresh token.
- **Static bearer API key** — what Claude Code, Cursor, and raw MCP clients
  use. Paste `Authorization: Bearer nk_...` in the MCP client config.

## Tools

| Tool | Purpose |
| --- | --- |
| `search_contacts` | Substring or field-exact search |
| `get_contact` | Single contact by id |
| `create_contact` | Create a new contact |
| `update_contact` | Patch an existing contact |
| `search_companies` | Substring or domain search |
| `create_company` | Create a new company |
| `list_pipelines` | List pipelines + stages for deal creation |
| `create_deal` | Create a deal; picks default pipeline + first stage if unspecified |
| `move_deal_stage` | Move a deal to a stage by slug (auto-sets status on won/lost stages) |
| `log_activity` | Log a call/meeting/email/etc. on any entity |
| `add_note` | Markdown note on any entity |
| `create_task` | Task on any entity |
| `list_tasks` | Filter tasks by status and assignee |
| `relate` | Add a typed edge between two entities (relationship graph) |
| `timeline` | Recent events for one entity |
| `describe_schema` | Return the full entity/field/event manifest |
| `memory_list_connectors` | Enabled memory connectors on this deployment |
| `memory_recall` | Fan-out recall across DocDeploy / Supermemory / GBrain / … |
| `memory_link` | Cross-link a memory id with a CRM entity |
| `memory_trace` | List all memories linked to one CRM entity |
| `ingest` | Normalize CSV / JSON / vCard / text and land it as CRM rows |

## Claude Desktop (custom connector, OAuth)

Open *Settings → Connectors → Add custom connector*:

- **Name:** Nakatomi
- **URL:** `https://your-app.up.railway.app/mcp`

Click *Connect*. Claude opens a browser tab, the Nakatomi login page
appears, you sign in with your Nakatomi email + password, pick a workspace
if you're in more than one, and consent. Claude stores the tokens.

No header to paste — Claude Desktop's connector UI doesn't expose that
field. It discovers our OAuth endpoints via `/.well-known/oauth-authorization-server`
and handles the PKCE flow itself.

## Cursor

Cursor's MCP config lives at `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "nakatomi": {
      "url": "https://your-app.up.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer nk_your_key_here"
      }
    }
  }
}
```

## Claude Code

```json
{
  "mcpServers": {
    "nakatomi": {
      "type": "http",
      "url": "https://your-app.up.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer nk_your_key_here"
      }
    }
  }
}
```

Drop this into `~/.claude/mcp_servers.json` (or the equivalent settings file for
your Claude Code version) and restart.

## Claude Agent SDK

```python
from anthropic import Anthropic

client = Anthropic()
# Connect to Nakatomi via the MCP connector in agent configuration.
# Consult the SDK docs for the current connector config schema.
```

## Local usage (no Railway)

If you're running Nakatomi locally with `docker compose up`, the MCP URL is
`http://localhost:8000/mcp`. Seed a key with `./install.sh --seed you@example.com`
and use it as the bearer.

## Tips

- **Always start with `describe_schema`** if your agent hasn't interacted with
  this workspace before. It returns the authoritative shape of every entity.
- **Prefer `external_id`** for idempotent upserts from automation. Re-runs
  become safe.
- **Use `relate` liberally.** A rich relationship graph means better downstream
  reasoning. Typical edges: `contact --works_at--> company`, `contact
  --decision_maker--> deal`, `company --partner_of--> company`.
- **`timeline` is your memory.** Before acting on an entity, call `timeline`
  and review the last N events. Avoids redundant updates.
