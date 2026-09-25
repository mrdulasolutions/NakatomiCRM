"""Shared HTML shells for OAuth and operator-facing auth pages."""

from __future__ import annotations

from html import escape

STATIC_BG = "/static/nakatomi-plaza-bg.jpg"

_BASE_STYLES = """
  :root {
    color-scheme: light;
    --ink: #0d0d0d;
    --muted: #5c5c5c;
    --line: rgba(0, 0, 0, 0.1);
    --panel: rgba(255, 255, 255, 0.94);
    --accent: #0a0a0a;
    --ok: #1b6b45;
    --ok-bg: #e8f5ee;
    --err: #8b1e1e;
    --err-bg: #fdecec;
    --focus: #111;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: "Segoe UI", ui-sans-serif, system-ui, -apple-system, Roboto, "Helvetica Neue", sans-serif;
    color: var(--ink);
    background: #e8e4dc url("%%BG_URL%%") center 35% / cover no-repeat fixed;
  }
  .scene {
    min-height: 100%;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    padding: clamp(28px, 6vw, 96px);
    background: linear-gradient(
      105deg,
      rgba(255, 255, 255, 0.94) 0%,
      rgba(255, 255, 255, 0.82) 38%,
      rgba(255, 255, 255, 0.45) 62%,
      rgba(255, 255, 255, 0.15) 100%
    );
  }
  .panel {
    width: min(440px, 100%);
    background: var(--panel);
    border: 1px solid var(--line);
    box-shadow: 0 28px 90px rgba(0, 0, 0, 0.14);
    border-radius: 3px;
    padding: clamp(28px, 4vw, 40px);
    backdrop-filter: blur(6px);
  }
  .mark {
    font-size: 10px;
    letter-spacing: 0.38em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 0 0 10px;
  }
  h1 {
    font-size: clamp(1.35rem, 2.5vw, 1.65rem);
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0 0 8px;
    line-height: 1.2;
  }
  .lede {
    color: var(--muted);
    font-size: 14px;
    line-height: 1.55;
    margin: 0 0 22px;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 8px 12px;
    border-radius: 2px;
    margin-bottom: 18px;
  }
  .badge.ok { background: var(--ok-bg); color: var(--ok); border: 1px solid rgba(27, 107, 69, 0.2); }
  .badge.err { background: var(--err-bg); color: var(--err); border: 1px solid rgba(139, 30, 30, 0.18); }
  .client-box {
    background: #f7f6f3;
    border: 1px solid var(--line);
    border-radius: 2px;
    padding: 12px 14px;
    font-size: 13px;
    line-height: 1.5;
    margin-bottom: 20px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .client-box strong { color: var(--ink); font-weight: 600; }
  .scope { color: var(--ok); }
  label {
    display: block;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 16px 0 6px;
  }
  input, select, button, .btn {
    font: inherit;
    width: 100%;
    padding: 11px 12px;
    border-radius: 2px;
    border: 1px solid var(--line);
    background: #fff;
    color: var(--ink);
  }
  input:focus, select:focus {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  button, .btn {
    cursor: pointer;
    margin-top: 22px;
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    text-align: center;
    text-decoration: none;
    display: inline-block;
  }
  button:hover, .btn:hover { background: #222; }
  .btn.secondary {
    background: #fff;
    color: var(--ink);
    border-color: var(--line);
    margin-top: 10px;
  }
  .alert {
    font-size: 13px;
    line-height: 1.45;
    padding: 10px 12px;
    border-radius: 2px;
    margin: 14px 0 0;
  }
  .alert.err { background: var(--err-bg); color: var(--err); border: 1px solid rgba(139, 30, 30, 0.15); }
  .foot {
    margin-top: 22px;
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 0.04em;
  }
  .actions { margin-top: 8px; }
  .panel-wide { width: min(560px, 100%); }
  .row-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  @media (max-width: 520px) { .row-2 { grid-template-columns: 1fr; } }
  .links { margin-top: 18px; font-size: 13px; }
  .links a { color: var(--ink); font-weight: 600; }
  .key-box {
    display: block;
    padding: 12px 14px;
    background: #f7f6f3;
    border: 1px solid var(--line);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    word-break: break-all;
    margin: 10px 0 14px;
  }
  .warn-box {
    font-size: 13px;
    line-height: 1.45;
    padding: 10px 12px;
    background: #fff8e6;
    border: 1px solid rgba(120, 90, 0, 0.2);
    color: #5c4a00;
    margin-bottom: 16px;
  }
  .code-block {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.5;
    background: #f7f6f3;
    border: 1px solid var(--line);
    padding: 12px 14px;
    overflow-x: auto;
    white-space: pre-wrap;
    margin: 8px 0 16px;
  }
  h2.section {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 22px 0 8px;
  }
  .countdown { font-size: 13px; color: var(--muted); margin-top: 12px; }
"""


def esc(s: str) -> str:
    return escape(s, quote=True)


def _shell(*, title: str, body: str, extra_head: str = "", panel_class: str = "panel") -> str:
    styles = _BASE_STYLES.replace("%%BG_URL%%", STATIC_BG)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{esc(title)} · Nakatomi</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="light" />
{extra_head}
<style>{styles}</style>
</head>
<body>
<div class="scene">
  <div class="{panel_class}">
{body}
  </div>
</div>
</body>
</html>"""


def render_status_page(
    *,
    variant: str,
    title: str,
    headline: str,
    message: str,
    detail: str | None = None,
    primary_label: str | None = None,
    primary_href: str | None = None,
    secondary_label: str | None = None,
    secondary_href: str | None = None,
) -> str:
    badge_class = "ok" if variant == "success" else "err"
    badge_text = "Authorized" if variant == "success" else "Could not continue"
    detail_html = f'<p class="lede">{esc(detail)}</p>' if detail else ""
    actions: list[str] = []
    if primary_label and primary_href:
        actions.append(f'<a class="btn" href="{esc(primary_href)}">{esc(primary_label)}</a>')
    if secondary_label and secondary_href:
        actions.append(f'<a class="btn secondary" href="{esc(secondary_href)}">{esc(secondary_label)}</a>')
    actions_html = f'<div class="actions">{"".join(actions)}</div>' if actions else ""
    body = f"""
    <p class="mark">Nakatomi CRM</p>
    <span class="badge {badge_class}">{esc(badge_text)}</span>
    <h1>{esc(headline)}</h1>
    <p class="lede">{esc(message)}</p>
    {detail_html}
    {actions_html}
    <p class="foot">OAuth 2.1 · PKCE · MCP-ready</p>
"""
    return _shell(title=title, body=body)


def render_authorize_page(
    *,
    client_name: str,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    state: str,
    scope: str,
    code_challenge: str,
    code_challenge_method: str,
    email: str = "",
    error: str | None = None,
    workspace_select_html: str = "",
) -> str:
    error_html = f'<div class="alert err">{esc(error)}</div>' if error else ""
    body = f"""
    <p class="mark">Nakatomi CRM</p>
    <h1>Authorize application</h1>
    <p class="lede">Sign in to grant <strong>{esc(client_name)}</strong> access to your workspace via MCP.</p>
    <div class="client-box">
      Scope: <span class="scope">{esc(scope)}</span><br />
      Client: <strong>{esc(client_id[:12])}…</strong><br />
      Redirect: {esc(redirect_uri)}
    </div>
    <form method="post" action="/oauth/authorize">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" required autofocus value="{esc(email)}" />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" required />
      {workspace_select_html}
      {error_html}
      <input type="hidden" name="client_id" value="{esc(client_id)}" />
      <input type="hidden" name="redirect_uri" value="{esc(redirect_uri)}" />
      <input type="hidden" name="response_type" value="{esc(response_type)}" />
      <input type="hidden" name="state" value="{esc(state)}" />
      <input type="hidden" name="scope" value="{esc(scope)}" />
      <input type="hidden" name="code_challenge" value="{esc(code_challenge)}" />
      <input type="hidden" name="code_challenge_method" value="{esc(code_challenge_method)}" />
      <button type="submit">Sign in &amp; authorize</button>
    </form>
    <p class="foot">Secured with OAuth 2.1 and PKCE</p>
"""
    return _shell(title="Authorize", body=body)


def render_login_landing() -> str:
    body = """
    <p class="mark">Nakatomi CRM</p>
    <h1>Sign in</h1>
    <p class="lede">Human sign-in for MCP connectors happens through the OAuth flow started by your agent client (Claude Desktop, Cursor, ChatGPT, and others).</p>
    <p class="lede">Open your connector settings and add this server URL — you will be redirected here to authorize with your Nakatomi credentials.</p>
    <a class="btn" href="/docs">API documentation</a>
    <a class="btn secondary" href="/">Return home</a>
    <p class="foot">Need an account? Use bootstrap on a fresh install or ask your workspace admin.</p>
"""
    return _shell(title="Sign in", body=body)


def render_welcome_page(*, error: str | None = None, form_action: str = "/welcome/signup") -> str:
    error_html = f'<div class="alert err">{esc(error)}</div>' if error else ""
    body = f"""
    <p class="mark">Nakatomi CRM</p>
    <h1>Claim this instance</h1>
    <p class="lede">One form creates your workspace, owner account, and agent API key. The key is shown exactly once.</p>
    {error_html}
    <form method="post" action="{esc(form_action)}">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" required autocomplete="email" />
      <label for="password">Password (min 8 characters)</label>
      <input id="password" name="password" type="password" required minlength="8" autocomplete="new-password" />
      <label for="display_name">Your name (optional)</label>
      <input id="display_name" name="display_name" type="text" autocomplete="name" />
      <div class="row-2">
        <div>
          <label for="workspace_name">Workspace name</label>
          <input id="workspace_name" name="workspace_name" required value="My Workspace" />
        </div>
        <div>
          <label for="workspace_slug">Workspace slug</label>
          <input id="workspace_slug" name="workspace_slug" required pattern="[a-z0-9][a-z0-9_-]*" value="mine" />
        </div>
      </div>
      <button type="submit">Create workspace &amp; API key</button>
    </form>
    <p class="foot links">Already initialized? <a href="/oauth/login">Sign in</a> · <a href="/docs">Docs</a> · <a href="/schema">Schema</a></p>
"""
    return _shell(title="Welcome", body=body)


def render_bootstrap_success(
    *,
    api_key: str,
    workspace_slug: str,
    email: str,
    base_url: str,
) -> str:
    curl_example = (
        f"BASE={base_url}\n"
        f"KEY={api_key}\n"
        f'curl -H "Authorization: Bearer $KEY" -H "X-Workspace: {workspace_slug}" $BASE/contacts'
    )
    body = f"""
    <p class="mark">Nakatomi CRM</p>
    <span class="badge ok">Ready</span>
    <h1>Nakatomi is yours</h1>
    <p class="lede">Workspace <strong>{esc(workspace_slug)}</strong> is live. You ({esc(email)}) are the owner.</p>
    <h2 class="section">Your API key</h2>
    <code class="key-box">{esc(api_key)}</code>
    <div class="warn-box">Save this key now. Nakatomi never shows it again. Revoke and mint a new one if you lose it.</div>
    <h2 class="section">Wire up an agent</h2>
    <pre class="code-block">{esc(curl_example)}</pre>
    <p class="lede">For Claude Desktop or Cursor: add <strong>{esc(base_url)}</strong> as a custom connector — OAuth sign-in uses this email and password.</p>
    <a class="btn" href="/docs">Open API docs</a>
    <a class="btn secondary" href="/oauth/login">Connect via OAuth</a>
    <p class="foot links"><a href="/schema">Schema</a> · <a href="/">Home</a></p>
"""
    return _shell(title="Claimed", body=body, panel_class="panel panel-wide")


def render_already_initialized() -> str:
    body = """
    <p class="mark">Nakatomi CRM</p>
    <h1>Already initialized</h1>
    <p class="lede">This instance has an owner. Sign in through your MCP connector or use an API key from your workspace admin.</p>
    <a class="btn" href="/oauth/login">Sign in help</a>
    <a class="btn secondary" href="/">API home</a>
"""
    return _shell(title="Welcome", body=body)


def render_oauth_complete(*, client_name: str, continue_url: str, delay_seconds: int = 2) -> str:
    safe = esc(continue_url)
    extra = f'<meta http-equiv="refresh" content="{delay_seconds};url={safe}" />'
    body = f"""
    <p class="mark">Nakatomi CRM</p>
    <span class="badge ok">Authorized</span>
    <h1>You are connected</h1>
    <p class="lede"><strong>{esc(client_name)}</strong> can access your workspace. Returning you to the application…</p>
    <p class="countdown">Continuing in {delay_seconds} seconds.</p>
    <a class="btn" href="{safe}">Continue now</a>
    <p class="foot">OAuth 2.1 · PKCE · MCP-ready</p>
"""
    return _shell(title="Authorized", body=body, extra_head=extra)
