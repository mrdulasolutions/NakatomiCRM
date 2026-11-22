"""MCP streamable HTTP requires Bearer auth (401 without key)."""

from __future__ import annotations


def test_mcp_initialize_requires_auth(client):
    r = client.post(
        "/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert r.status_code == 401, r.text
    www = r.headers.get("www-authenticate") or r.headers.get("WWW-Authenticate") or ""
    assert "Bearer" in www or "bearer" in www.lower()
    assert "invalid_token" in r.text or "Authentication" in r.text or "auth" in r.text.lower()


def test_mcp_initialize_with_api_key(workspace, mcp_client):
    r = mcp_client.post(
        "/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {workspace['api_key']}",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert r.status_code == 200, r.text
    assert "Nakatomi" in r.text or "protocolVersion" in r.text

    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {workspace['api_key']}",
        "Mcp-Session-Id": r.headers["Mcp-Session-Id"],
        "MCP-Protocol-Version": "2024-11-05",
    }
    r = mcp_client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert r.status_code == 202, r.text
    r = mcp_client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_pipelines", "arguments": {}},
        },
    )
    assert r.status_code == 200, r.text
    assert '"isError":false' in r.text.replace(" ", ""), r.text


def test_oauth_protected_resource_mcp_path(client):
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert "authorization_servers" in body
    assert body.get("scopes_supported") == ["mcp", "mcp:write", "mcp:export"]
    assert body["resource"].endswith("/mcp")
