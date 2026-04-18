# Architecture

A quick visual tour of how Nakatomi is wired up. Diagrams are Mermaid with
the `handDrawn` look — see [`docs/diagrams/README.md`](./diagrams/README.md)
for editing notes.

## Component overview

```mermaid
%%{init: {"look": "handDrawn", "theme": "neutral"}}%%
flowchart LR
    Claude[Claude Desktop]
    ChatGPT[ChatGPT]
    Cursor[Cursor]
    Perplexity[Perplexity]
    CLI[curl / scripts]

    Claude & ChatGPT & Cursor & Perplexity --> MCP
    CLI --> REST

    subgraph Nakatomi[Nakatomi CRM]
        direction TB
        REST[REST API<br/>/contacts /deals /timeline /...]
        MCP[MCP server<br/>/mcp]
        Worker[Webhook worker<br/>background thread]
        Schema[/schema + llms.txt + agent.json/]
    end

    REST & MCP & Worker --> PG[(Postgres)]
    REST --> Storage[(File storage<br/>local volume or S3)]
    REST & MCP -.->|optional| Memory[Memory connectors<br/>DocDeploy / Supermemory / GBrain]
    Worker -.->|HTTP POST signed| Sub[Subscribers]
```

Every box at the top is an existing agent host. Every arrow into the
Nakatomi subgraph carries `Authorization: Bearer nk_<key>`. The Schema
cluster (`/schema`, `/llms.txt`, `/.well-known/agent.json`) is how agents
discover capabilities before doing anything else.

## Durable webhook delivery

```mermaid
%%{init: {"look": "handDrawn", "theme": "neutral"}}%%
sequenceDiagram
    participant Route as REST route
    participant Emit as emit()
    participant DB as Postgres
    participant Worker as Webhook worker
    participant HTTP as subscriber URL

    Route->>Emit: contact.created
    Emit->>DB: INSERT WebhookDelivery<br/>status=pending
    Note over Worker: polls every 5s<br/>SELECT ... FOR UPDATE SKIP LOCKED
    Worker->>DB: claim pending row
    Worker->>HTTP: POST signed payload
    alt 2xx response
        HTTP-->>Worker: 200 OK
        Worker->>DB: status=succeeded
    else failure
        HTTP--xWorker: 5xx / timeout
        Worker->>DB: attempts++, schedule retry
        Note over Worker: after WEBHOOK_MAX_RETRIES<br/>→ status=dead
    end
```

The worker thread starts in FastAPI's `lifespan`. `SELECT ... FOR UPDATE
SKIP LOCKED` makes multiple app processes safe — they race to claim rows
and don't step on each other.

## Ingest pipeline

```mermaid
%%{init: {"look": "handDrawn", "theme": "neutral"}}%%
flowchart LR
    Source[Agent call /<br/>UI upload /<br/>paste] -->|POST /ingest| Dispatch{format}
    Dispatch -->|csv| CSV[csv adapter]
    Dispatch -->|json| JSON[json adapter]
    Dispatch -->|vcard| VCard[vcard adapter]
    Dispatch -->|text| Text[text adapter]

    CSV & JSON & VCard & Text --> Norm[Normalize<br/>lowercase email<br/>E.164 phone<br/>canonicalize URL]
    Norm --> Dedupe[Dedupe<br/>external_id → email/domain]
    Dedupe --> CRM[(CRM rows)]
    Dedupe -.->|ingest.completed event| Timeline[[timeline + audit log]]
```

Agents do the hard reasoning (extract entities from a PDF, reconcile fields
from two sources); Nakatomi standardizes the shape. The `dry_run` flag lets
you preview what would change before committing.

## Export / import round-trip

```mermaid
%%{init: {"look": "handDrawn", "theme": "neutral"}}%%
flowchart LR
    WS1[(Workspace A<br/>source)] -->|GET /export| JSON[["nakatomi-&lt;slug&gt;-&lt;date&gt;.json"]]
    JSON -->|POST /import<br/>merge-upsert| WS2[(Workspace B<br/>target)]
    JSON -.->|stays portable| Anywhere[any Nakatomi<br/>instance]

    subgraph Rules
        direction TB
        R1[natural-key match<br/>external_id → email / domain / slug]
        R2[UUIDs regenerated<br/>no pk collisions across installs]
        R3[polymorphic refs rewritten<br/>notes, tasks, activities, memory_links]
    end
```

Webhook secrets are redacted on export and re-minted on import. File bytes
aren't inline (v2 tarball extension) — the manifest points at them; fetch
via `GET /files/{id}` if you need them on the other side.

## Memory cross-linking

```mermaid
%%{init: {"look": "handDrawn", "theme": "neutral"}}%%
flowchart LR
    Write[CRM mutation<br/>contact.created / deal.won / ...] --> Emit[emit event]
    Emit --> TL[(timeline)]
    Emit --> Hooks[webhook queue]
    Emit -.->|configured connectors| Conn[DocDeploy / Supermemory / GBrain]
    Conn --> Link[(MemoryLink row<br/>connector + external_id<br/>↕ crm_entity_type + id)]

    Read[memory_recall query] --> Fan[fan-out to all connectors]
    Fan --> Conn
    Conn --> Merge[merge + sort by score]
    Merge --> Return[return with crm_links<br/>per result]
```

The `MemoryLink` table is the bidirectional bridge. Every outbound store
creates one; every inbound webhook from a memory system creates one; every
recall decorates results with the links already on file so the agent can
pivot between structured and semantic in a single call.

## Why this shape

A few design claims the diagrams make visible:

1. **One Postgres is the source of truth.** No Redis, no Kafka, no
   eventual-consistency story to explain. The durable webhook queue and
   the rate-limit counter both live in Postgres rows.
2. **The worker is in-process.** For v1 that's fine — `SELECT ... FOR
   UPDATE SKIP LOCKED` makes it safe to scale horizontally. When volume
   justifies it, the same function that runs in the thread can be pulled
   out into a dedicated worker process with zero logic changes.
3. **Memory is always plural.** The recall fan-out design means agents can
   enable a cheap connector (Supermemory) and a self-hosted one (GBrain)
   at the same time without the CRM caring which is authoritative.
4. **Agents discover through /schema.** We don't ship SDK stubs or
   generated clients — the agent asks, learns, and acts. That's the whole
   point of MCP.
