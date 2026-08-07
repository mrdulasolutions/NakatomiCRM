# Observability (v1.0)

## Always on

| Signal | Where |
| --- | --- |
| `X-Request-Id` | Every response (echo inbound or generate UUID) |
| Access log | `method path status ms request_id actor` (API key prefix only) |
| `/health` | Liveness + version + protocol block + OTel status |
| `/health/deep` | Same + Postgres ping (503 if down) |

## Optional OpenTelemetry

Disabled by default. No hard dependency — missing packages log a warning
and continue.

### Enable

```bash
pip install opentelemetry-api opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-http \
  opentelemetry-instrumentation-fastapi \
  opentelemetry-instrumentation-httpx \
  opentelemetry-instrumentation-sqlalchemy
```

```env
OTEL_ENABLED=true
OTEL_SERVICE_NAME=nakatomi
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
# optional: OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer xxx
```

When enabled, Nakatomi:

1. Installs a `TracerProvider` with service resource attributes
2. Exports spans via OTLP/HTTP if an endpoint is set
3. Instruments FastAPI, httpx, and SQLAlchemy when those instrumentors
   are installed

Check status:

```bash
curl -s localhost:8000/health | jq .otel
python -m app check-config
```

### What we intentionally skip (for now)

- Metrics/logs exporters (add when a deploy needs them)
- Auto-instrumentation of MCP stream sessions as first-class spans
  (HTTP layer still traces)

Keep PII out of custom span attributes. Prefer entity ids over emails.
