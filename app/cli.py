"""Thin operator CLI for Nakatomi v1.0+.

Usage::

    python -m app.cli version
    python -m app.cli health [--url http://localhost:8000]
    python -m app.cli protocols
    python -m app.cli check-config

No heavy deps — stdlib + httpx (already a runtime dependency).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def cmd_version(_: argparse.Namespace) -> int:
    from app import __version__
    from app.protocol import PROTOCOL_VERSIONS, STABILITY_TIER

    print(
        json.dumps(
            {"version": __version__, "stability": STABILITY_TIER, "protocols": PROTOCOL_VERSIONS}, indent=2
        )
    )
    return 0


def cmd_protocols(_: argparse.Namespace) -> int:
    from app.protocol import protocol_manifest

    print(json.dumps(protocol_manifest(), indent=2))
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    import httpx

    url = args.url.rstrip("/") + ("/health/deep" if args.deep else "/health")
    try:
        r = httpx.get(url, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc), "url": url}), file=sys.stderr)
        return 2
    try:
        body: Any = r.json()
    except Exception:  # noqa: BLE001
        body = {"raw": r.text[:500]}
    print(json.dumps({"status_code": r.status_code, "body": body}, indent=2))
    return 0 if r.status_code == 200 and (isinstance(body, dict) and body.get("ok", True)) else 1


def cmd_check_config(_: argparse.Namespace) -> int:
    from app.config import settings
    from app.otel import is_available
    from app.otel import status as otel_status

    issues: list[str] = []
    warnings: list[str] = []
    prod = settings.ENVIRONMENT.lower() in {"production", "prod"}
    insecure_secrets = {
        "",
        "insecure-dev-key-change-me",
        "change-me-to-a-long-random-string",
        "dev-only-change-me-0123456789abcdef",
    }
    if prod:
        if settings.SECRET_KEY in insecure_secrets:
            issues.append("SECRET_KEY is a known insecure default — set a strong secret before production")
        elif len(settings.SECRET_KEY) < 32:
            warnings.append("SECRET_KEY is shorter than 32 characters")
        if settings.CORS_ORIGINS.strip() == "*":
            warnings.append(
                "CORS_ORIGINS is '*' — prefer explicit origins in production (credentials are enabled)"
            )
        if settings.API_KEY_RATE_LIMIT_PER_MINUTE <= 0:
            warnings.append(
                "API_KEY_RATE_LIMIT_PER_MINUTE is disabled — recommend e.g. 120 for production agent keys"
            )
        if not settings.BOOTSTRAP_TOKEN.strip():
            warnings.append(
                "BOOTSTRAP_TOKEN is unset — public deploys can be claimed by anyone until the first user exists"
            )
        if settings.AUTH_RATE_LIMIT_PER_MINUTE <= 0:
            warnings.append(
                "AUTH_RATE_LIMIT_PER_MINUTE is disabled — recommend e.g. 30 for /auth/login and /bootstrap"
            )
        sso_enabled = bool(
            (settings.SSO_GOOGLE_CLIENT_ID and settings.SSO_GOOGLE_CLIENT_SECRET)
            or (settings.SSO_GITHUB_CLIENT_ID and settings.SSO_GITHUB_CLIENT_SECRET)
        )
        if sso_enabled and not settings.PUBLIC_BASE_URL.strip():
            warnings.append("SSO is configured but PUBLIC_BASE_URL is empty — OAuth redirects may be wrong")
    elif settings.SECRET_KEY in insecure_secrets:
        warnings.append("SECRET_KEY is a documented dev default — change before production")
    if settings.OTEL_ENABLED and not is_available():
        warnings.append("OTEL_ENABLED=true but OpenTelemetry packages are not installed")
    sso = {
        "google": bool(settings.SSO_GOOGLE_CLIENT_ID and settings.SSO_GOOGLE_CLIENT_SECRET),
        "github": bool(settings.SSO_GITHUB_CLIENT_ID and settings.SSO_GITHUB_CLIENT_SECRET),
    }
    report = {
        "environment": settings.ENVIRONMENT,
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "sso": sso,
        "otel": otel_status(),
        "database_driver": "psycopg" if "+psycopg" in settings.DATABASE_URL else "unknown",
    }
    print(json.dumps(report, indent=2))
    return 1 if issues else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nakatomi", description="Nakatomi operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ver = sub.add_parser("version", help="print app + protocol versions")
    p_ver.set_defaults(func=cmd_version)

    p_proto = sub.add_parser("protocols", help="print protocol SLA manifest")
    p_proto.set_defaults(func=cmd_protocols)

    p_health = sub.add_parser("health", help="probe a running instance")
    p_health.add_argument("--url", default="http://localhost:8000")
    p_health.add_argument("--deep", action="store_true", help="hit /health/deep")
    p_health.set_defaults(func=cmd_health)

    p_cfg = sub.add_parser("check-config", help="validate local env for production readiness")
    p_cfg.set_defaults(func=cmd_check_config)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
