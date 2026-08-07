"""Optional OpenTelemetry wiring.

Enabled only when ``OTEL_ENABLED=true`` **and** the OpenTelemetry packages
are installed. Missing packages degrade to no-ops so production can ship
without a hard dependency.

Install for full export::

    pip install opentelemetry-api opentelemetry-sdk \\
                opentelemetry-exporter-otlp-proto-http \\
                opentelemetry-instrumentation-fastapi \\
                opentelemetry-instrumentation-httpx \\
                opentelemetry-instrumentation-sqlalchemy

Env (standard OTEL + Nakatomi):

- ``OTEL_ENABLED`` — master switch (default false)
- ``OTEL_SERVICE_NAME`` — default ``nakatomi``
- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — e.g. ``http://localhost:4318``
- ``OTEL_EXPORTER_OTLP_HEADERS`` — optional ``k=v,k2=v2``
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

log = logging.getLogger("nakatomi.otel")

_initialized = False
_tracer_provider: Any = None


def is_available() -> bool:
    try:
        import opentelemetry  # noqa: F401

        return True
    except ImportError:
        return False


def setup_otel(app: Any | None = None) -> bool:
    """Initialize tracer provider + optional FastAPI instrumentation.

    Returns True if tracing is active.
    """
    global _initialized, _tracer_provider
    if _initialized:
        return _tracer_provider is not None

    from app.config import settings

    _initialized = True
    if not settings.OTEL_ENABLED:
        log.debug("OTel disabled (OTEL_ENABLED=false)")
        return False

    if not is_available():
        log.warning(
            "OTEL_ENABLED=true but opentelemetry packages are not installed; "
            "tracing is a no-op. See docs/OBSERVABILITY.md"
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.OTEL_SERVICE_NAME,
                "service.version": __import__("app").__version__,
                "deployment.environment": settings.ENVIRONMENT,
            }
        )
        provider = TracerProvider(resource=resource)

        endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip()
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            headers = _parse_headers(settings.OTEL_EXPORTER_OTLP_HEADERS)
            exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", headers=headers or None)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info("OTel OTLP exporter → %s", endpoint)
        else:
            log.info("OTel enabled without OTLP endpoint (spans stay in-process only)")

        trace.set_tracer_provider(provider)
        _tracer_provider = provider

        if app is not None:
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                FastAPIInstrumentor.instrument_app(app)
            except Exception as exc:  # noqa: BLE001
                log.warning("FastAPI OTel instrumentation skipped: %s", exc)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception:  # noqa: BLE001
            pass

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            from app.db import engine

            SQLAlchemyInstrumentor().instrument(
                engine=engine.sync_engine if hasattr(engine, "sync_engine") else engine
            )
        except Exception:  # noqa: BLE001
            pass

        log.info("OpenTelemetry tracing active (service=%s)", settings.OTEL_SERVICE_NAME)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("OTel setup failed: %s", exc)
        _tracer_provider = None
        return False


def shutdown_otel() -> None:
    global _tracer_provider
    if _tracer_provider is not None:
        with suppress(Exception):
            _tracer_provider.shutdown()
        _tracer_provider = None


def _parse_headers(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def status() -> dict[str, Any]:
    from app.config import settings

    return {
        "enabled": bool(settings.OTEL_ENABLED),
        "packages_installed": is_available(),
        "active": _tracer_provider is not None,
        "service_name": settings.OTEL_SERVICE_NAME,
        "endpoint_configured": bool((settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip()),
    }
