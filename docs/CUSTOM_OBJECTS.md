# Custom objects

Moldable CRM model without a second database. Define a type, then store records
as JSON values with optional links back to core entities (contact/company/deal).

## Types

```
POST /custom-objects/types
{
  "name": "Partner",
  "slug": "partner",
  "fields": [
    {"name": "region", "label": "Region", "type": "string", "required": true},
    {"name": "tier", "label": "Tier", "type": "select", "options": ["A","B","C"]}
  ]
}
```

## Records

```
POST /custom-objects/types/partner/records
{
  "name": "Acme Supply",
  "external_id": "partner-1",
  "values": {"region": "APAC", "tier": "A"},
  "related_entity_type": "company",
  "related_entity_id": "<company uuid>"
}
```

Upsert is automatic when `external_id` matches.

MCP: `list_object_types`, `create_object_type`, `upsert_record`, `search_records`.

Scopes: `custom_fields:read` / `custom_fields:write`.

## Custom fields on core entities

For properties on contact/company/deal (not a whole new noun), define a
**custom field** instead of a custom object:

| MCP tool | Role |
| --- | --- |
| `list_custom_fields` | read registry |
| `create_custom_field` | owner/admin + `custom_fields:write` |
| `update_custom_field` | patch label/type/required/options |
| `delete_custom_field` | drop definition (values in `data` remain) |
| `describe_schema` | core entities + **this workspace's** fields/types |

REST: `GET/POST /custom-fields`, `PATCH/DELETE /custom-fields/{id}`.

Values live on each row's `data` JSONB under the field `name`.

## When to use

- **Custom field** — property of a core entity (e.g. `linkedin_url` on contact)
- **Custom object** — new noun that is not universal CRM (partners, SKU packs, milestones)
- **Not** a substitute for leads/deals/contacts — use first-class types for those
