"""Operator CLI check-config tests."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from app.cli import cmd_check_config


def test_check_config_production_warns_on_defaults():
    args = type("Args", (), {})()
    with patch("app.config.settings") as settings:
        settings.ENVIRONMENT = "production"
        settings.SECRET_KEY = "insecure-dev-key-change-me"
        settings.CORS_ORIGINS = "*"
        settings.API_KEY_RATE_LIMIT_PER_MINUTE = 0
        settings.AUTH_RATE_LIMIT_PER_MINUTE = 0
        settings.BOOTSTRAP_TOKEN = ""
        settings.PUBLIC_BASE_URL = ""
        settings.SSO_GOOGLE_CLIENT_ID = ""
        settings.SSO_GOOGLE_CLIENT_SECRET = ""
        settings.SSO_GITHUB_CLIENT_ID = ""
        settings.SSO_GITHUB_CLIENT_SECRET = ""
        settings.OTEL_ENABLED = False
        with patch("app.otel.is_available", return_value=True):
            with patch("app.otel.status", return_value={"enabled": False}):
                with patch("sys.stdout", new=StringIO()) as out:
                    code = cmd_check_config(args)
    report = json.loads(out.getvalue())
    assert code == 1
    assert report["ok"] is False
    assert any("SECRET_KEY" in i for i in report["issues"])
    assert len(report["warnings"]) >= 4
