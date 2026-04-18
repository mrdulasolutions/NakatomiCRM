---
name: nakatomi-crm
description: Use this skill whenever the user is operating on their Nakatomi CRM — creating, updating, finding, or deleting contacts, companies, deals, activities, notes, tasks, files, relationships. Trigger on mentions of "nakatomi", "the CRM", "my pipeline", "my deals", "add a contact", "log a call", "move a deal to …", or references to a Nakatomi workspace slug. Also trigger when the user asks to link a memory to a CRM entity or pull CRM context into their agent.
---

# Nakatomi CRM — usage rules for agents

Nakatomi is a headless CRM. There is no UI. Everything happens through REST or
MCP. When this skill fires, apply these rules.

## 1. Start with `describe_schema`

If this is your first interaction with this workspace in the current session,
call `describe_schema` (MCP) or `GET /schema` (REST) once and hold the result
in context. It lists every entity, its fields, and the full event catalog.

## 2. Authentication

- REST: `Authorization: Bearer nk_<key>`
- MCP: same header, configured once in the MCP client

Never paste the API key into the conversation. If the user hasn't configured
one yet, instruct them to run `POST /workspace/api-keys` or the `seed` script.

## 3. Reads before writes

Before mutating an entity, read its current state and its `timeline`:

- MCP: `get_contact`, `timeline(entity_type, entity_id)`
- REST: `GET /contacts/{id}`, `GET /timeline/{entity_type}/{entity_id}`

This avoids redundant updates and preserves the audit story.

## 4. Upsert with `external_id`

When importing or syncing from an external system (CSV, HubSpot, Apollo, a
PDF extract), set `external_id` to the stable id from that source.
`POST /contacts/bulk_upsert` will match on `external_id` first, then on
`email`. Re-running the same import is then idempotent.

## 5. Use the relationship graph

Don't treat entities as islands. When you create or update a contact, also
`relate` them:

- `contact --works_at--> company`
- `contact --decision_maker--> deal`
- `company --partner_of--> company`
- `contact --reports_to--> contact`

Downstream agents query `/relationships/neighbors?entity_type=contact&entity_id=…&depth=2`
to find who's adjacent.

## 6. Log activities generously

Every call, meeting, email-you-sent-from-Gmail, and Slack DM that matters
becomes an `activity` attached to the relevant entity. Kind strings are
free-form — settle on `call`, `meeting`, `email_log`, `dm`, `voice_note`
and stay consistent.

## 7. Soft delete

`DELETE /contacts/{id}` soft-deletes by default. Only pass `?hard=true` if
the human explicitly asks. The default exists so a human can recover from an
agent mistake.

## 8. Idempotency for critical writes

For actions the human would hate to see duplicated (creating a deal,
advancing a deal to won), include an `Idempotency-Key` header. Replays
return the original response.

## 9. Don't invent fields

Every entity has a `data` JSONB column for free-form attributes. Use it
instead of making up columns that don't exist. If you find yourself
needing the same field repeatedly, surface it to the user as a candidate
for a first-class column in a future Nakatomi release.

## 10. Link memories

If the user has a memory system plugged in (DocDeploy, Supermemory, etc.),
after creating rich context (a long note, a call transcript, a deal brief),
`POST /memory/link` to cross-reference the memory id with the CRM entity.
That way, later `POST /memory/recall` calls surface the right memory for
the right entity.

## 11. Read the timeline, don't rebuild it

Never try to "reconstruct history" from field values. The `timeline_events`
feed already has every mutation with actor and payload. Use it.

## Common tool flows

- **Log a call:** `get_contact → log_activity(kind="call", subject, body, entity_type=contact, entity_id) → add_note(if transcript) → create_task(if follow-up)`
- **Move a deal:** `get_deal → list_pipelines → move_deal_stage(deal_id, stage_slug)`
- **Onboard a company:** `create_company → for each contact: create_contact(+ company_id) → relate(contact, works_at, company)`
- **Morning review:** `timeline(workspace, since=yesterday) → list_tasks(status=open, due_before=today+1d)`

## Anti-patterns

- Calling `search_contacts` with no query when you meant to list — use
  pagination (`GET /contacts?limit=50&cursor=…`) instead.
- Creating duplicate contacts because you forgot the `external_id`.
- Hard-deleting as cleanup. Use soft delete. Always.
- Skipping the timeline and re-deriving history from the current row.
- Writing to a field that doesn't exist. Use `data`.

## When unsure

Call `describe_schema` again. It's the source of truth for what's possible
in this deployment — operators can disable endpoints, add memory connectors,
or enable the dashboard at will.
