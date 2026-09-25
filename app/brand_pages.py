"""Shared HTML shells for OAuth, operator auth, and the audit dashboard."""

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


def render_dashboard_disabled() -> str:
    body = """
    <p class="mark">Nakatomi CRM</p>
    <h1>Audit dashboard is off</h1>
    <p class="lede">This deployment has the read-only audit UI disabled. Agents should use the REST API and MCP with a workspace API key.</p>
    <p class="lede">To enable locally, set <strong>DASHBOARD_ENABLED=true</strong> and restart the app, then open <strong>/dashboard</strong> again.</p>
    <a class="btn" href="/docs">API documentation</a>
    <a class="btn secondary" href="/">Home</a>
    <p class="foot">Do not enable on public URLs without additional access control.</p>
"""
    return _shell(title="Dashboard", body=body)


_DASHBOARD_STYLES = """
  body.dash-app { margin: 0; min-height: 100%; }
  .dash-shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: linear-gradient(
      105deg,
      rgba(255, 255, 255, 0.94) 0%,
      rgba(255, 255, 255, 0.86) 42%,
      rgba(255, 255, 255, 0.55) 100%
    );
  }
  .dash-header {
    padding: 14px clamp(16px, 4vw, 28px);
    border-bottom: 1px solid var(--line);
    display: flex;
    gap: 16px;
    align-items: center;
    flex-wrap: wrap;
    background: rgba(255, 255, 255, 0.72);
    backdrop-filter: blur(8px);
  }
  .dash-brand { min-width: 160px; }
  .dash-brand .mark { margin: 0 0 4px; }
  .dash-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .dash-meta {
    font-size: 12px;
    color: var(--muted);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .dash-nav { display: flex; gap: 6px; flex-wrap: wrap; }
  .dash-nav button {
    width: auto;
    margin: 0;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    background: #fff;
    color: var(--muted);
    border: 1px solid var(--line);
  }
  .dash-nav button.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }
  .dash-btn-ghost {
    width: auto;
    margin: 0;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    background: #fff;
    color: var(--muted);
    border: 1px solid var(--line);
    border-radius: 2px;
    cursor: pointer;
  }
  .dash-btn-ghost:hover { background: #f7f6f3; color: var(--ink); }
  .dash-main { padding: clamp(12px, 3vw, 20px); flex: 1; }
  .dash-main[hidden],
  .dash-auth-wrap[hidden] {
    display: none !important;
  }
  .dash-shell.dash-authed .dash-auth-wrap {
    display: none !important;
  }
  .dash-view { display: none; }
  .dash-view.active { display: block; }
  .dash-auth-wrap {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 16px 64px;
  }
  .dash-auth {
    width: min(440px, 100%);
    background: var(--panel);
    border: 1px solid var(--line);
    box-shadow: 0 28px 90px rgba(0, 0, 0, 0.12);
    border-radius: 3px;
    padding: clamp(28px, 4vw, 40px);
    backdrop-filter: blur(6px);
  }
  .dash-auth h2 {
    margin: 0 0 8px;
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .dash-auth .lede { margin-bottom: 16px; }
  .dash-auth input { margin-top: 0; }
  .dash-auth button#save {
    margin-top: 18px;
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .dash-toolbar {
    padding: 8px 4px 12px;
    color: var(--muted);
    font-size: 11px;
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .dash-toolbar .accent { color: var(--ink); font-weight: 600; }
  .dash-select {
    padding: 6px 10px;
    background: #fff;
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 2px;
    font: inherit;
    width: auto;
  }
  .dash-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
  }
  .dash-section {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid var(--line);
    border-radius: 3px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    max-height: 80vh;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06);
  }
  .dash-section h2 {
    margin: 0;
    padding: 10px 14px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    background: #f7f6f3;
    border-bottom: 1px solid var(--line);
    color: var(--muted);
  }
  .dash-section .body {
    padding: 8px 14px;
    overflow: auto;
    font-size: 12px;
    line-height: 1.55;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .dash-row { padding: 6px 0; border-bottom: 1px dashed var(--line); }
  .dash-row:last-child { border-bottom: none; }
  .dash-row .k { color: var(--ink); font-weight: 600; }
  .dash-row .t { color: var(--muted); font-size: 11px; }
  .dash-empty { opacity: 0.55; padding: 12px 0; color: var(--muted); }
  .pipe-label {
    padding: 8px 4px;
    color: var(--muted);
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  .kanban {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(240px, 1fr);
    gap: 12px;
    overflow-x: auto;
    padding-bottom: 8px;
  }
  .kanban .col {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid var(--line);
    border-radius: 3px;
    display: flex;
    flex-direction: column;
    max-height: 75vh;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06);
  }
  .kanban .col h3 {
    margin: 0;
    padding: 10px 14px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    background: #f7f6f3;
    border-bottom: 1px solid var(--line);
    display: flex;
    justify-content: space-between;
    gap: 8px;
  }
  .kanban .col h3 .won { color: var(--ok); }
  .kanban .col h3 .lost { color: var(--err); }
  .kanban .col h3 .count { color: var(--ink); font-weight: normal; }
  .kanban .stack {
    padding: 8px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .kanban .card {
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 2px;
    padding: 10px;
    font-size: 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .kanban .card .name { color: var(--ink); font-weight: 600; margin-bottom: 4px; overflow-wrap: anywhere; }
  .kanban .card .meta { color: var(--muted); font-size: 11px; }
  .kanban .card .amt { color: var(--ok); font-size: 11px; }
  .wh-item {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid var(--line);
    border-radius: 3px;
    margin-bottom: 10px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
  }
  .wh-head {
    padding: 10px 14px;
    cursor: pointer;
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .wh-head:hover { background: #f7f6f3; }
  .wh-name { color: var(--ink); font-size: 13px; font-weight: 600; }
  .wh-url {
    color: var(--muted);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .wh-badge {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    border: 1px solid var(--line);
    color: var(--muted);
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .wh-badge.fail { color: var(--err); border-color: rgba(139, 30, 30, 0.25); background: var(--err-bg); }
  .wh-badge.ok { color: var(--ok); border-color: rgba(27, 107, 69, 0.25); background: var(--ok-bg); }
  .wh-badge.off { color: var(--muted); }
  .wh-body { border-top: 1px solid var(--line); padding: 10px 14px; background: #fff; }
  .wh-delivery {
    padding: 8px 0;
    border-bottom: 1px dashed var(--line);
    font-size: 11px;
    line-height: 1.5;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .wh-delivery:last-child { border-bottom: none; }
  .wh-delivery .status {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 2px;
    font-size: 10px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-right: 6px;
  }
  .wh-delivery .status.succeeded { background: var(--ok-bg); color: var(--ok); }
  .wh-delivery .status.dead { background: var(--err-bg); color: var(--err); }
  .wh-delivery .status.pending { background: #f0ecff; color: #4a3a7a; }
  .wh-delivery .event { color: var(--ink); font-weight: 600; }
  .wh-delivery .meta { color: var(--muted); }
  .wh-delivery .meta.err { color: var(--err); }
  .wh-delivery pre {
    margin: 4px 0 0 0;
    padding: 6px 8px;
    background: #f7f6f3;
    border: 1px solid var(--line);
    border-radius: 2px;
    font-size: 10px;
    color: var(--ink);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 200px;
    overflow: auto;
  }
  .mem-link {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid var(--line);
    border-radius: 3px;
    padding: 10px 14px;
    margin-bottom: 8px;
    font-size: 12px;
    display: grid;
    grid-template-columns: auto auto 1fr auto;
    gap: 12px;
    align-items: center;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .mem-link .pill {
    padding: 2px 8px;
    border-radius: 10px;
    border: 1px solid var(--line);
    font-size: 10px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .mem-link .pill.connector { color: #4a3a7a; border-color: rgba(74, 58, 122, 0.25); background: #f0ecff; }
  .mem-link .pill.entity { color: var(--ok); border-color: rgba(27, 107, 69, 0.25); background: var(--ok-bg); }
  .mem-link .ref { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mem-link .ref .mono { color: var(--ink); }
  .mem-link .t { color: var(--muted); font-size: 10px; }
  .mem-link .note {
    grid-column: 1 / -1;
    color: var(--muted);
    font-size: 11px;
    padding-top: 4px;
    border-top: 1px dashed var(--line);
    margin-top: 6px;
  }
  .mem-load-more {
    display: block;
    width: 100%;
    padding: 8px;
    margin-top: 8px;
    background: #fff;
    color: var(--ink);
    border: 1px dashed var(--line);
    border-radius: 2px;
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .mem-total { padding: 4px; color: var(--ink); font-size: 11px; font-weight: 600; }
  @media (max-width: 720px) {
    .dash-header { gap: 10px; }
    .dash-nav { width: 100%; }
  }
"""


def dashboard_stylesheet() -> str:
    """CSS shared with OAuth/welcome (Plaza background + audit dashboard layout)."""
    return _BASE_STYLES.replace("%%BG_URL%%", STATIC_BG) + _DASHBOARD_STYLES
