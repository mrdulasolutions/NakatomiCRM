# MCP ↔ REST parity matrix

Rule: every capability remains available over REST. MCP is a curated agent
surface — not 1:1 with every route.

| Domain | REST | MCP tools | Notes |
| --- | --- | --- | --- |
| Context boot | `GET /acp/context` | `load_context` | ACP pack |
| Discovery | `GET /discovery`, `/schema` | `describe_schema` | |
| Contacts | `/contacts/*` | `search_contacts`, `get_contact`, `create_contact`, `update_contact` | |
| Companies | `/companies/*` | `search_companies`, `create_company` | |
| Account map | compose REST | **`upsert_account_map`** | compound |
| Pipelines | `/pipelines/*` | `list_pipelines`, `create_pipeline` | |
| Deals | `/deals/*` | `create_deal`, `move_deal_stage`, **`advance_deal`** | |
| Products / lines | `/products`, `/deals/…/line-items` | `create_product`, `search_products`, `add_line_item`, `list_line_items` | |
| Forecast | `GET /forecast` | `forecast` | |
| Activities | `/activities/*` | `log_activity`, **`log_interaction`** | |
| Notes | `/notes/*` | `add_note` | |
| Tasks | `/tasks/*` | `create_task`, `list_tasks` | |
| Relationships | `/relationships/*` | `relate` | |
| Timeline | `/timeline/*` | `timeline` | |
| Open work | compose | **`morning_briefing`** | compound |
| Entity state | **`GET /agent/entity-context`** | **`entity_context`** | timeline + per-section resource reads |
| Workforce facts | **`GET /agent/activity`** | **`agent_activity`** | timeline aggregates |
| Agent roster | **`GET /agent/agents`** | **`list_agents`** | API key identities |
| Explain change | **`GET /agent/explain-change`** | **`explain_change`** | audit + timeline |
| Handoff | **`POST /agent/handoff`** | (compose) | returns entity_context |
| Memory | `/memory/*` | `memory_*` | |
| Ingest | `POST /ingest` | `ingest` | |
| Email | `/email/*` | `send_email` | needs `email:send` |
| Calendar | `/calendar/*` | `add_calendar_feed`, `sync_calendar_feed` | |
| Approvals | `/approvals/*` | `propose_action`, `list_pending_approvals`, `decide_approval` | |
| A2A tasks | `/a2a/tasks/*` | REST preferred | MCP later if needed |
| Files | `/files/*` | REST only | multipart |
| Export/import | `/export`, `/import` | REST only | large payloads |
| Webhooks admin | `/webhooks/*` | REST only | |
| Custom fields | `/custom-fields/*` | `list_custom_fields`, `create_custom_field`, `update_custom_field`, `delete_custom_field` | owner/admin for mutations; also in ACP pack + `describe_schema` |
| Custom objects | `/custom-objects/*` | `list_object_types`, `create_object_type`, `upsert_record`, `search_records` | moldable model |

## Compound tools (prefer these)

| Tool | Scopes | Does |
| --- | --- | --- |
| `load_context` | auth | ACP pack |
| `entity_context` | timeline:read + resource reads per section | Entity business-state bundle (P5) |
| `morning_briefing` | tasks/deals/approvals read | Open work |
| `agent_activity` | timeline:read | Workforce facts from timeline |
| `list_agents` | workspace:read | Agent identity roster |
| `explain_change` | timeline:read | Evidence chain |
| `upsert_account_map` | companies+contacts+relationships write | Company + contacts + edges |
| `advance_deal` | deals write (+ activity/task) | Stage + optional activity/task |
| `log_interaction` | activities write (+ notes) | Activity + optional note |
