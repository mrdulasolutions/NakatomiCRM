"""v1.0 polish: protocol SLA, SSO discovery, OTel status, CLI."""

from __future__ import annotations

from app.cli import main as cli_main
from app.protocol import PROTOCOL_VERSIONS, SUNSET_NOTICE_DAYS, protocol_manifest


def test_protocol_manifest_shape():
    m = protocol_manifest()
    assert m["stability"] == "stable"
    assert m["sunset_notice_days"] == SUNSET_NOTICE_DAYS == 90
    assert set(m["versions"]) == {"rest", "mcp", "a2a", "acp"}
    for v in m["versions"].values():
        assert v == "1.0"


def test_health_exposes_protocols(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == "1.0.0"
    assert body["stability"] == "stable"
    assert body["protocols"] == PROTOCOL_VERSIONS
    assert "otel" in body
    assert body["otel"]["enabled"] is False


def test_schema_and_discovery_sla(client):
    r = client.get("/schema")
    assert r.status_code == 200
    s = r.json()
    assert s["protocols"]["mcp"] == "1.0"
    assert s["stability"] == "stable"
    assert s["sunset_notice_days"] == 90
    assert isinstance(s["scheduled_sunsets"], list)

    r = client.get("/discovery")
    assert r.status_code == 200
    d = r.json()
    assert d["protocols"]["versions"]["a2a"] == "1.0"
    assert "sso_providers" in d["links"]


def test_sso_providers_disabled_by_default(client):
    r = client.get("/auth/sso/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["any"] is False
    assert body["enabled"]["google"] is False
    assert body["enabled"]["github"] is False


def test_sso_start_unavailable_without_config(client):
    r = client.get("/auth/sso/google", follow_redirects=False)
    assert r.status_code == 503


def test_cli_version_and_protocols(capsys):
    assert cli_main(["version"]) == 0
    out = capsys.readouterr().out
    assert "1.0.0" in out
    assert cli_main(["protocols"]) == 0
    assert "sunset_notice_days" in capsys.readouterr().out
    assert cli_main(["check-config"]) == 0
