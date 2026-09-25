# Nakatomi in 5 minutes

How long from zero to an **agent operating your CRM**? This path is the answer we optimize for.

You will:

1. Start Nakatomi
2. Create a workspace and API key
3. Connect an MCP client
4. Run one natural-language CRM workflow through your agent
5. Verify the same data over REST

No marketing copy—just the loop that proves the thesis.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/nakatomicrm)

Prefer one-click? Deploy above (~60–90s), set `PUBLIC_BASE_URL` to your Railway HTTPS origin, then use that URL everywhere this doc says `localhost:8000`. Template details: [RAILWAY_TEMPLATE.md](./RAILWAY_TEMPLATE.md).

---

## 1. Start Nakatomi

**Railway (fastest if you do not want local Docker):** use the button at the top of this page, wait for `/health`, then continue at step 2 with your `*.up.railway.app` URL.

**Docker (local):**

```bash
git clone https://github.com/mrdulasolutions/NakatomiCRM.git
cd NakatomiCRM
cp .env.example .env   # set SECRET_KEY (openssl rand -hex 32)
docker compose up -d
curl -s http://localhost:8000/health
```

Expect `"ok": true` and a `version` field.

**Already on Railway?** Use your public URL instead of `localhost:8000` for every step below.

---

## 2. Create a workspace and API key

**Option A — browser (fresh install):** open `http://localhost:8000/` and complete the welcome form. Copy the `nk_…` key when shown (once only).

**Option B — CLI:**

```bash
./install.sh --seed you@example.com
# or: python -m scripts.seed --email you@example.com --password '…' \
#       --workspace-name "Demo" --workspace-slug demo
```

Save the printed **`nk_…`** key somewhere safe.

---

## 3. Connect an MCP client

Endpoint (same host as `/health`):

```text
http://localhost:8000/mcp
```

Header (static key — Cursor, Claude Code, most dev clients):

```text
Authorization: Bearer nk_your_key_here
```

**Cursor** — MCP settings, add a server pointing at your URL with that header. Full recipes: [MCP.md](./MCP.md).

**Claude Desktop** — Custom Connector can use OAuth against your Nakatomi URL, or configure a bearer key if your client supports it.

First tool call your agent should make in a new session: **`describe_schema`** (or `GET /schema` over REST). That loads entity shapes and the event catalog once.

---

## 4. The killer demo (one agent turn)

Paste this into your connected agent:

```text
Using Nakatomi MCP, do the following in order:

1. Call describe_schema if you have not already this session.
2. Create company Acme Corp (domain acme.com if useful).
3. Create contact John Smith, email john@acme.com, title CTO.
4. Create deal "Enterprise Deployment" for $25,000 USD in the default pipeline.
5. Relate John Smith to Acme Corp and associate the contact with the deal as appropriate.
6. Summarize what you created and pull timeline entries for the deal.
```

**What “success” looks like** (shape, not exact IDs):

| Object | You should see |
| --- | --- |
| Company | Acme Corp |
| Contact | John Smith · john@acme.com |
| Deal | Enterprise Deployment · ~$25,000 |
| Graph | Contact linked to company (and deal if your agent used `relate`) |
| Timeline | Multiple `*.created` / relationship events |

That single turn is the product: **structured state + graph + audit**, not a chat summary.

---

## 5. Verify over REST (optional but recommended)

Replace `KEY` and `HOST`:

```bash
export HOST=http://localhost:8000
export KEY=nk_your_key_here

curl -s -H "Authorization: Bearer $KEY" "$HOST/companies?limit=5" | head -c 400
curl -s -H "Authorization: Bearer $KEY" "$HOST/contacts?limit=5" | head -c 400
curl -s -H "Authorization: Bearer $KEY" "$HOST/deals?limit=5" | head -c 400
```

Pick a deal id from the deals response, then:

```bash
curl -s -H "Authorization: Bearer $KEY" "$HOST/timeline?entity_type=deal&entity_id=DEAL_ID&limit=20"
```

If MCP and REST disagree, something is wrong with auth or workspace—not with the agent’s story.

---

## 6. What to do when something breaks

| Symptom | Likely fix |
| --- | --- |
| `/health` fails | Postgres not up; `docker compose ps`, check `DATABASE_URL` |
| MCP 401 | Missing or wrong `Authorization: Bearer nk_…` on **every** MCP request |
| MCP 405 on `/` | Client pointed at site root; use **`/mcp`** |
| 403 missing scopes | Mint a key with `*` or add `contacts:write`, `companies:write`, `deals:write`, `relationships:write` |
| No pipeline for deal | Fresh workspace should seed defaults; call `list_pipelines` or create via MCP |
| OAuth vs key confusion | Desktop “connector” OAuth ≠ Cursor static header — see [MCP.md](./MCP.md) |

Production checklist: [DEPLOY.md](./DEPLOY.md). Operator sanity: `python -m app check-config`.

---

## 7. Cold takeover (P5)

After any agent has worked an account, a **new** session can continue without chat history:

```text
GET /agent/entity-context?entity_type=company&entity_ref=Acme%20Corp
```

Or MCP: `entity_context("company", "Acme Corp")`.

Mint **separate keys per role** — see [AGENT-WORKFORCE-KEYS.md](./AGENT-WORKFORCE-KEYS.md).

Full multi-agent script: [demos/WORKFORCE-DEMO.md](./demos/WORKFORCE-DEMO.md).

---

## After the five minutes

- **Business-state layer for agent workforces:** [AGENT-OS.md](./AGENT-OS.md) (P5 roadmap: `entity_context`, attribution, handoffs)
- **Orchestrated workforce (Paperclip reference):** [integrations/PAPERCLIP.md](./integrations/PAPERCLIP.md)
- **Patterns for real GTM agents:** [AgentLab.md](../AgentLab.md)
- **Tool reference:** [MCP.md](./MCP.md)
- **Memory connectors (optional):** [MEMORY.md](./MEMORY.md)
- **Local audit UI (dev):** `DASHBOARD_ENABLED=true` → `/dashboard`

When this path works end-to-end on your machine, the README has done its job—you are evaluating **behavior**, not prose.
