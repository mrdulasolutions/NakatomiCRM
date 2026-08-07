# CRM imports

Agent-driven one-shot migrations. **No mapping UI** — agents reshape exports
into the documented payload shapes (or use `generic` + `mapping`).

## Endpoint

```
POST /import/crm
Authorization: Bearer nk_…
Content-Type: application/json

{
  "source": "hubspot|salesforce|pipedrive|attio|generic",
  "payload": { ... },
  "mapping": { },      // optional, generic only
  "dry_run": true
}
```

Scope: `export:write` (or `*`).

MCP: `import_crm(source, payload, mapping?, dry_run?)`.

## Sources

| Source | Payload shape |
| --- | --- |
| **hubspot** | `{ contacts, companies, deals, notes }` — each may be a list of `{id, properties}` |
| **salesforce** | `{ Account, Contact, Opportunity }` or lower-case + optional `{records:[…]}` |
| **pipedrive** | `{ persons, organizations, deals }` or API wrappers with `data: []` |
| **attio** | `{ companies, people, deals }` — supports Attio `values` arrays |
| **generic** | `{ companies, contacts, deals }` with Nakatomi field names; optional mapping |

## Workflow for agents

1. `dry_run: true` — inspect `created` / `updated` counts and `errors`
2. Fix mapping / payload
3. `dry_run: false` — commit
4. Use returned `id_map_sample` / re-search by `external_id` (`hs-contact-…`, `sf-account-…`, etc.)

External IDs are namespaced so re-imports upsert cleanly.
