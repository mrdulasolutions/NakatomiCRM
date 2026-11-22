"""Workspace dashboard and browser-authenticated agent management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.brand_pages import dashboard_stylesheet, render_dashboard_disabled
from app.browser_sessions import (
    browser_principal,
    clear_session,
    public_origin,
    require_same_origin,
    set_session,
)
from app.config import settings
from app.db import get_db
from app.deps import Principal
from app.models import ApiKey, MemberRole, Membership, OAuthClient, Workspace
from app.oauth_grants import oauth_metadata, oauth_scopes, revoke_grant
from app.routers.auth import login
from app.schemas import LoginRequest
from app.security import generate_api_key

router = APIRouter(tags=["dashboard"])


_DASHBOARD_HTML = (
    """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Audit dashboard · Nakatomi</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <style>
"""
    + dashboard_stylesheet()
    + """
  </style>
</head>
<body class="dash-app">
<div class="dash-shell">
<header class="dash-header">
  <div class="dash-brand">
    <p class="mark">Nakatomi CRM</p>
    <h1 class="dash-title">Audit dashboard</h1>
  </div>
  <span id="ws" class="dash-meta"></span>
  <nav class="dash-nav">
    <button type="button" data-view="audit" class="active">Audit</button>
    <button type="button" data-view="kanban">Kanban</button>
    <button type="button" data-view="webhooks">Webhooks</button>
    <button type="button" data-view="memory">Memory</button>
    <button type="button" data-view="agents" id="agents-tab" hidden>Connect an agent</button>
  </nav>
  <span style="flex:1"></span>
  <select id="workspace-picker" aria-label="Workspace" hidden></select>
  <button type="button" id="logout" class="dash-btn-ghost">Sign out</button>
</header>

<div id="auth-wrap" class="dash-auth-wrap" hidden>
  <div id="auth" class="dash-auth">
    <p class="mark">Nakatomi CRM</p>
    <h2>Sign in</h2>
    <form id="login-form">
      <label for="email">Email</label>
      <input id="email" type="email" autocomplete="username" required />
      <label for="password">Password</label>
      <input id="password" type="password" autocomplete="current-password" required />
      <button type="submit">Sign in</button>
    </form>
    <div id="sso-links"></div>
    <div id="auth-error" class="alert err" hidden role="alert"></div>
  </div>
</div>

<main id="app" class="dash-main" hidden>
  <div id="view-audit" class="dash-view active">
    <div class="dash-grid">
      <section class="dash-section"><h2>Timeline</h2><div class="body" id="timeline"></div></section>
      <section class="dash-section"><h2>Recent contacts</h2><div class="body" id="contacts"></div></section>
      <section class="dash-section"><h2>Recent companies</h2><div class="body" id="companies"></div></section>
      <section class="dash-section"><h2>Deals</h2><div class="body" id="deals"></div></section>
      <section class="dash-section"><h2>Open tasks</h2><div class="body" id="tasks"></div></section>
      <section class="dash-section"><h2>Webhook deliveries</h2><div class="body" id="webhooks"></div></section>
    </div>
  </div>
  <div id="view-kanban" class="dash-view">
    <div id="pipe-label" class="pipe-label">Pipeline</div>
    <div class="kanban" id="kanban"></div>
  </div>
  <div id="view-webhooks" class="dash-view">
    <div id="wh-controls" class="dash-toolbar">
      <span>Status filter</span>
      <select id="wh-filter" class="dash-select">
        <option value="">All</option>
        <option value="pending">Pending</option>
        <option value="succeeded">Succeeded</option>
        <option value="dead">Dead</option>
      </select>
      <span style="flex:1"></span>
  <select id="workspace-picker" aria-label="Workspace" hidden></select>
      <button type="button" id="wh-refresh" class="dash-btn-ghost">Refresh</button>
    </div>
    <div id="wh-root"></div>
  </div>
  <div id="view-memory" class="dash-view">
    <div class="dash-toolbar">
      <span>Connectors</span>
      <span id="mem-connectors" class="accent">—</span>
      <span style="flex:1"></span>
  <select id="workspace-picker" aria-label="Workspace" hidden></select>
      <span>Filter</span>
      <select id="mem-connector-filter" class="dash-select">
        <option value="">All connectors</option>
      </select>
      <select id="mem-entity-filter" class="dash-select">
        <option value="">All entities</option>
        <option value="contact">Contact</option>
        <option value="company">Company</option>
        <option value="deal">Deal</option>
        <option value="activity">Activity</option>
        <option value="note">Note</option>
        <option value="task">Task</option>
        <option value="file">File</option>
      </select>
      <button type="button" id="mem-refresh" class="dash-btn-ghost">Refresh</button>
    </div>
    <div id="mem-total" class="mem-total"></div>
    <div id="mem-root"></div>
  </div>
  <div id="view-agents" class="dash-view">
    <section class="dash-section">
      <h2>Connect an agent</h2>
      <p>Use this Streamable HTTP URL for Grok, DOTs, or another MCP client.</p>
      <code id="agent-url"></code>
      <p>Browser-based clients can request OAuth consent. For Grok API or a headless bot, create a dedicated credential and store it in the bot’s secret store.</p>
      <form id="agent-form">
        <label for="agent-name">Agent name</label>
        <input id="agent-name" required maxlength="120" />
        <label><input id="agent-write" type="checkbox" /> Allow CRM writes</label>
        <label><input id="agent-export" type="checkbox" /> Allow workspace ZIP exports</label>
        <button type="submit">Create credential</button>
      </form>
      <p id="agent-message" role="status"></p>
      <code id="agent-token"></code>
      <button type="button" id="test-agent" hidden>Test connection</button>
      <ul id="agent-list"></ul>
    </section>
  </div>
</main>
</div>

<script>
async function sessionRequest(path, method, data) {
  const response = await fetch(path, {
    method,
    headers: data ? {"Content-Type": "application/json"} : {},
    body: data ? JSON.stringify(data) : undefined,
    cache: "no-store",
  });
  if (response.ok) return response.status === 204 ? null : response.json();
  const body = await response.json().catch(() => ({}));
  throw Object.assign(new Error(typeof body.detail === "string" ? body.detail : "Request failed"), {status: response.status});
}

async function loadAgents() {
  const {url, agents} = await sessionRequest("/dashboard/agents", "GET");
  document.getElementById("agent-url").textContent = url;
  const list = document.getElementById("agent-list");
  list.replaceChildren();
  for (const agent of agents) {
    const item = document.createElement("li");
    const access = (agent.scopes || []).some(scope => scope.endsWith(":write")) ? "Read and write" : "Read only";
    item.textContent = `${agent.name} · ${access} · ${agent.last_used_at ? new Date(agent.last_used_at).toLocaleString() : "Never used"} `;
    const button = document.createElement("button");
    button.textContent = "Disconnect";
    button.onclick = async () => {
      try {
        await sessionRequest(`/dashboard/agents/${agent.id}`, "DELETE");
        await loadAgents();
      } catch (error) { document.getElementById("agent-message").textContent = error.message; }
    };
    item.append(button);
    list.append(item);
  }
}

function showAuthError(msg) {
  setDashboardAuth(true);
  const err = document.getElementById("auth-error");
  err.hidden = false;
  err.textContent = msg;
}

function setDashboardAuth(showLogin) {
  document.querySelector(".dash-shell").classList.toggle("dash-authed", !showLogin);
  document.getElementById("auth-wrap").hidden = !showLogin;
  document.getElementById("app").hidden = showLogin;
}

async function api(path) {
  const r = await fetch(path, { headers: { "X-Nakatomi-Dashboard": "1" }, cache: "no-store" });
  if (!r.ok) {
    let detail = `${path} → HTTP ${r.status}`;
    try {
      const body = await r.json();
      if (body && body.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch (e) { /* non-JSON */ }
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.json();
}
function cell(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text ?? "";
  return element;
}
function row(key, text, time) {
  const item = document.createElement("div");
  item.className = "dash-row";
  item.append(cell("span", "k", key), " ", text ?? "");
  if (time) item.append(cell("div", "t", time));
  return item;
}
function empty() { const d = document.createElement("div"); d.className = "dash-empty"; d.textContent = "— nothing yet —"; return d; }

function fmtMoney(amt, cur) {
  if (amt == null) return "";
  const n = Number(amt);
  if (Number.isNaN(n)) return "";
  return `${(cur||"USD")} ${n.toLocaleString("en-US", {minimumFractionDigits: 0, maximumFractionDigits: 2})}`;
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"})[c]); }

async function loadAudit() {
  const ws = await api("/workspace");
  document.getElementById("ws").textContent = `workspace: ${ws.slug}`;

  const tl = await api("/timeline?limit=40");
  const tlEl = document.getElementById("timeline"); tlEl.innerHTML = "";
  if (!tl.items.length) tlEl.appendChild(empty());
  tl.items.forEach(e => tlEl.appendChild(row(e.event_type, `${e.entity_type}:${e.entity_id.slice(0,8)}`, e.occurred_at)));

  const c = await api("/contacts?limit=20");
  const cEl = document.getElementById("contacts"); cEl.innerHTML = "";
  if (!c.items.length) cEl.appendChild(empty());
  c.items.forEach(x => cEl.appendChild(row(`${x.first_name||""} ${x.last_name||""}`.trim()||"(no name)", x.email || "", x.created_at)));

  const co = await api("/companies?limit=20");
  const coEl = document.getElementById("companies"); coEl.innerHTML = "";
  if (!co.items.length) coEl.appendChild(empty());
  co.items.forEach(x => coEl.appendChild(row(x.name, x.domain || "", x.created_at)));

  const d = await api("/deals?limit=20");
  const dEl = document.getElementById("deals"); dEl.innerHTML = "";
  if (!d.items.length) dEl.appendChild(empty());
  d.items.forEach(x => dEl.appendChild(row(x.name, `${x.status} · ${fmtMoney(x.amount, x.currency)}`, x.updated_at)));

  const t = await api("/tasks?status=open&limit=20");
  const tEl = document.getElementById("tasks"); tEl.innerHTML = "";
  if (!t.items.length) tEl.appendChild(empty());
  t.items.forEach(x => tEl.appendChild(row(x.title, x.due_at ? `due ${x.due_at}` : "", x.created_at)));

  const wh = await api("/webhooks");
  const whEl = document.getElementById("webhooks"); whEl.innerHTML = "";
  if (!wh.length) whEl.appendChild(empty());
  wh.forEach(x => whEl.appendChild(row(x.name, `${x.url} · failures=${x.failure_count}`, x.last_delivery_at || "(never fired)")));
}

async function loadKanban() {
  const pipes = await api("/pipelines");
  const kEl = document.getElementById("kanban"); kEl.innerHTML = "";
  const labelEl = document.getElementById("pipe-label");

  if (!pipes.length) {
    labelEl.textContent = "pipeline: (none configured)";
    kEl.appendChild(empty());
    return;
  }

  // Pick the default pipeline, or the first one.
  const pipe = pipes.find(p => p.is_default) || pipes[0];
  labelEl.textContent = `pipeline: ${pipe.name}  ·  ${pipe.stages.length} stages`;

  // Fetch every open deal in this pipeline, paginated.
  const deals = [];
  let cursor = null;
  for (let i = 0; i < 20; i++) {
    const qs = new URLSearchParams({ pipeline_id: pipe.id, limit: "200" });
    if (cursor) qs.set("cursor", cursor);
    const page = await api(`/deals?${qs}`);
    deals.push(...page.items);
    if (!page.next_cursor || page.items.length === 0) break;
    cursor = page.next_cursor;
  }

  // Group by stage_id.
  const byStage = new Map();
  for (const s of pipe.stages) byStage.set(s.id, []);
  for (const d of deals) {
    if (!byStage.has(d.stage_id)) byStage.set(d.stage_id, []);
    byStage.get(d.stage_id).push(d);
  }

  // Render columns in stage order.
  for (const stage of pipe.stages) {
    const col = document.createElement("div"); col.className = "col";
    const h3 = document.createElement("h3");
    h3.append(cell("span", stage.is_won ? "won" : stage.is_lost ? "lost" : "", stage.name));
    const items = byStage.get(stage.id) || [];
    const total = items.reduce((acc, d) => acc + Number(d.amount || 0), 0);
    h3.append(" ", cell("span", "count", `${items.length}${total ? ` · ${fmtMoney(total, items[0]?.currency || "USD")}` : ""}`));
    col.appendChild(h3);
    const stack = document.createElement("div"); stack.className = "stack";
    if (!items.length) {
      const e = document.createElement("div"); e.className = "empty"; e.textContent = "—"; stack.appendChild(e);
    }
    for (const d of items) {
      const card = document.createElement("div"); card.className = "card";
      const close = d.expected_close_date ? ` · close ${new Date(d.expected_close_date).toLocaleDateString()}` : "";
      card.append(cell("div", "name", d.name), cell("div", "amt", fmtMoney(d.amount, d.currency)),
                  cell("div", "meta", `${d.status}${close}`));
      stack.appendChild(card);
    }
    col.appendChild(stack);
    kEl.appendChild(col);
  }
}

async function loadWebhooks() {
  const filter = document.getElementById("wh-filter").value;
  const hooks = await api("/webhooks");
  const root = document.getElementById("wh-root");
  root.innerHTML = "";
  if (!hooks.length) { root.appendChild(empty()); return; }

  for (const hook of hooks) {
    const item = document.createElement("div"); item.className = "wh-item";
    const badgeClass = !hook.is_active ? "off" : hook.failure_count > 0 ? "fail" : "ok";
    const badgeText  = !hook.is_active ? "disabled" : hook.failure_count > 0 ? `${hook.failure_count} failures` : "healthy";
    const head = document.createElement("div"); head.className = "wh-head";
    head.innerHTML = `
      <div class="wh-name">${esc(hook.name)}</div>
      <div class="wh-url">${esc(hook.url)}</div>
      <span class="wh-badge ${badgeClass}">${esc(badgeText)}</span>
      <span class="meta">${hook.last_delivery_at ? "Last: " + new Date(hook.last_delivery_at).toLocaleString() : "Never fired"}</span>
    `;
    const body = document.createElement("div"); body.className = "wh-body"; body.hidden = true;

    head.addEventListener("click", async () => {
      if (body.hidden) {
        body.hidden = false;
        body.innerHTML = '<div class="meta">loading…</div>';
        try {
          const deliveries = await api(`/webhooks/${hook.id}/deliveries?limit=50`);
          const filtered = filter ? deliveries.filter(d => d.status === filter) : deliveries;
          body.innerHTML = "";
          if (!filtered.length) { body.appendChild(empty()); return; }
          for (const d of filtered) {
            const row = document.createElement("div"); row.className = "wh-delivery";
            const status = d.status || (d.succeeded ? "succeeded" : "pending");
            const parts = [`<span class="status ${esc(status)}">${esc(status)}</span>`];
            parts.push(`<span class="event">${esc(d.event_type)}</span>`);
            parts.push(`<span class="meta"> · attempt ${esc(d.attempts)}`);
            if (d.status_code != null) parts.push(` · http ${esc(d.status_code)}`);
            parts.push(` · ${new Date(d.created_at).toLocaleString()}</span>`);
            if (d.error) parts.push(`<div class="meta err">Error: ${esc(d.error)}</div>`);
            if (d.response_body) parts.push(`<pre>${esc(d.response_body.slice(0, 400))}</pre>`);
            row.innerHTML = parts.join("");
            body.appendChild(row);
          }
        } catch (err) {
          body.innerHTML = `<div class="meta err">Failed: ${esc(err.message)}</div>`;
        }
      } else {
        body.hidden = true;
      }
    });

    item.appendChild(head);
    item.appendChild(body);
    root.appendChild(item);
  }
}

let _memCursor = null;
let _memEnabledConnectors = null;

function updateConnectorBanner(enabled, linkItems) {
  const el = document.getElementById("mem-connectors");
  const linked = [...new Set((linkItems || []).map(l => l.connector))].sort();
  if (enabled.length) {
    el.textContent = linked.length && linked.some(c => !enabled.includes(c))
      ? `${enabled.join(", ")} · links also: ${linked.filter(c => !enabled.includes(c)).join(", ")}`
      : enabled.join(", ");
  } else if (linked.length) {
    el.textContent = `MEMORY_CONNECTORS off · ${linked.length} linked: ${linked.join(", ")}`;
  } else {
    el.textContent = "none enabled";
  }
  const sel = document.getElementById("mem-connector-filter");
  const seen = new Set([...sel.options].map(o => o.value).filter(Boolean));
  for (const c of [...new Set([...enabled, ...linked])]) {
    if (seen.has(c)) continue;
    const opt = document.createElement("option"); opt.value = c; opt.textContent = c; sel.appendChild(opt);
    seen.add(c);
  }
}

async function loadMemory(reset = true) {
  if (reset) _memCursor = null;
  const connector = document.getElementById("mem-connector-filter").value;
  const entityType = document.getElementById("mem-entity-filter").value;

  if (_memEnabledConnectors === null) {
    try {
      _memEnabledConnectors = await api("/memory/connectors");
    } catch (e) {
      _memEnabledConnectors = [];
    }
  }

  const qs = new URLSearchParams({ limit: "50" });
  if (connector) qs.set("connector", connector);
  if (entityType) qs.set("entity_type", entityType);
  if (_memCursor) qs.set("cursor", _memCursor);

  const page = await api(`/memory/links?${qs}`);
  if (reset) {
    updateConnectorBanner(_memEnabledConnectors, page.items);
  }
  const root = document.getElementById("mem-root");
  const totalEl = document.getElementById("mem-total");
  if (reset) root.innerHTML = "";
  totalEl.textContent = `${page.count} link${page.count === 1 ? "" : "s"} total`;

  if (reset && !page.items.length) { root.appendChild(empty()); return; }

  for (const link of page.items) {
    const div = document.createElement("div"); div.className = "mem-link";
    const shortEid = link.crm_entity_id.slice(0, 8);
    const shortExt = (link.external_id || "").slice(0, 40);
    div.innerHTML = `
      <span class="pill connector">${esc(link.connector)}</span>
      <span class="pill entity">${esc(link.crm_entity_type)}</span>
      <span class="ref">→ <span class="mono">${esc(shortEid)}</span> · external: <span class="mono">${esc(shortExt)}</span></span>
      <span class="t">${new Date(link.created_at).toLocaleString()}</span>
      ${link.note ? `<div class="note">${esc(link.note)}</div>` : ""}
    `;
    root.appendChild(div);
  }

  // Remove any old "load more" button first.
  const prev = root.querySelector(".mem-load-more");
  if (prev) prev.remove();

  if (page.next_cursor) {
    _memCursor = page.next_cursor;
    const btn = document.createElement("button");
    btn.className = "mem-load-more";
    btn.textContent = `load 50 more`;
    btn.addEventListener("click", () => loadMemory(false));
    root.appendChild(btn);
  }
}

function switchView(name) {
  for (const b of document.querySelectorAll(".dash-nav button")) b.classList.toggle("active", b.dataset.view === name);
  for (const v of document.querySelectorAll(".dash-view")) v.classList.toggle("active", v.id === "view-" + name);
  if (name === "kanban") loadKanban().catch(err => { console.error(err); showAuthError(err.message); });
  if (name === "webhooks") loadWebhooks().catch(err => { console.error(err); showAuthError(err.message); });
  if (name === "memory") loadMemory().catch(err => { console.error(err); showAuthError(err.message); });
}

let _uiWired = false;
function wireUi() {
  if (_uiWired) return;
  _uiWired = true;
  for (const b of document.querySelectorAll(".dash-nav button")) b.addEventListener("click", () => switchView(b.dataset.view));
  document.getElementById("wh-refresh").addEventListener("click", () => loadWebhooks());
  document.getElementById("wh-filter").addEventListener("change", () => loadWebhooks());
  document.getElementById("mem-refresh").addEventListener("click", () => loadMemory());
  document.getElementById("mem-connector-filter").addEventListener("change", () => loadMemory());
  document.getElementById("mem-entity-filter").addEventListener("change", () => loadMemory());
}

try { sessionStorage.removeItem("nk_dashboard_key"); } catch (_) {}

async function init() {
  try {
    const session = await sessionRequest("/dashboard/session", "GET");
    const picker = document.getElementById("workspace-picker");
    picker.replaceChildren(...session.workspaces.map(ws => new Option(ws.name, ws.id)));
    picker.value = session.workspace_id;
    picker.hidden = session.workspaces.length < 2;
    const role = session.workspaces.find(ws => ws.id === session.workspace_id)?.role;
    document.getElementById("agents-tab").hidden = !["owner", "admin"].includes(role);
    document.getElementById("auth-error").hidden = true;
    setDashboardAuth(false);
    await loadAudit();
    wireUi();
  } catch (error) {
    if (error.status === 401) {
      document.getElementById("workspace-picker").hidden = true;
      setDashboardAuth(true);
      const links = document.getElementById("sso-links");
      links.replaceChildren();
      try {
        const providers = await sessionRequest("/auth/sso/providers", "GET");
        for (const name of ["google", "github"]) {
          if (providers.enabled[name]) {
            const link = document.createElement("a");
            link.href = `/auth/sso/${name}?dashboard=true`;
            link.textContent = name === "google" ? "Continue with Google" : "Continue with GitHub";
            links.append(link, document.createElement("br"));
          }
        }
      } catch (_) { /* Password login remains available. */ }
    } else {
      showAuthError(error.message);
    }
  }
}

document.getElementById("login-form").onsubmit = async event => {
  event.preventDefault();
  const password = document.getElementById("password");
  try {
    await sessionRequest("/dashboard/session", "POST", {email: document.getElementById("email").value, password: password.value});
    await init();
  } catch (error) { showAuthError(error.message); }
  finally { password.value = ""; }
};
document.getElementById("logout").onclick = async () => {
  try {
    await sessionRequest("/dashboard/session", "DELETE");
    window.location.reload();
  } catch (error) { showAuthError(error.message); }
};
document.getElementById("workspace-picker").onchange = async event => {
  try {
    await sessionRequest("/dashboard/workspace", "POST", {workspace_id: event.target.value});
    window.location.reload();
  } catch (error) { showAuthError(error.message); }
};
document.getElementById("agents-tab").addEventListener("click", () => loadAgents().catch(error => {
  document.getElementById("agent-message").textContent = error.message;
}));
document.getElementById("agent-form").onsubmit = async event => {
  event.preventDefault();
  const message = document.getElementById("agent-message");
  const output = document.getElementById("agent-token");
  output.textContent = "";
  document.getElementById("test-agent").hidden = true;
  try {
    const result = await sessionRequest("/dashboard/agents", "POST", {
      name: document.getElementById("agent-name").value,
      can_write: document.getElementById("agent-write").checked,
      can_export: document.getElementById("agent-export").checked,
    });
    output.textContent = result.token;
    document.getElementById("test-agent").hidden = false;
    message.textContent = "Copy this credential now. It will only be shown once.";
    event.target.reset();
    await loadAgents();
  } catch (error) { message.textContent = error.message; }
};

document.getElementById("test-agent").onclick = async () => {
  const token = document.getElementById("agent-token").textContent;
  const message = document.getElementById("agent-message");
  const headers = {
    Accept: "application/json, text/event-stream",
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
  async function send(method, params, id) {
    const response = await fetch("/mcp", {
      method: "POST", headers,
      body: JSON.stringify({jsonrpc: "2.0", method, params, id}),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`MCP ${method} returned HTTP ${response.status}`);
    if (id === undefined) return {response};
    const text = await response.text();
    const data = text.startsWith("{") ? text : text.split("\\n").find(line => line.startsWith("data:"))?.slice(5);
    const body = JSON.parse(data || "{}");
    if (!body.result || body.result.isError) throw new Error(`MCP ${method} failed`);
    return {response, result: body.result};
  }
  try {
    const {response, result} = await send("initialize", {
      protocolVersion: "2024-11-05", capabilities: {}, clientInfo: {name: "Nakatomi dashboard", version: "1"},
    }, 1);
    headers["MCP-Protocol-Version"] = result.protocolVersion;
    const sessionId = response.headers.get("Mcp-Session-Id");
    if (sessionId) headers["Mcp-Session-Id"] = sessionId;
    await send("notifications/initialized");
    await send("tools/call", {name: "list_pipelines", arguments: {}}, 2);
    message.textContent = "Connection verified with a read-only MCP tool.";
    await loadAgents();
  } catch (error) { message.textContent = error.message; }
  finally {
    if (headers["Mcp-Session-Id"]) await fetch("/mcp", {method: "DELETE", headers}).catch(() => {});
  }
};

init();
</script>
</body>
</html>
"""
)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    if not settings.DASHBOARD_ENABLED:
        return HTMLResponse(render_dashboard_disabled(), status_code=404)
    response = HTMLResponse(_DASHBOARD_HTML, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})
    if request.cookies.get("nk_dashboard_key"):
        response.delete_cookie("nk_dashboard_key")
    return response


def _require_dashboard() -> None:
    if not settings.DASHBOARD_ENABLED:
        raise HTTPException(404, "Dashboard is disabled")


def _session_info(db: Session, user_id: str, workspace_id: str) -> dict:
    workspaces = db.execute(
        select(Workspace.id, Workspace.name, Membership.role)
        .join(Membership)
        .where(Membership.user_id == user_id)
        .order_by(Workspace.name, Workspace.id)
    )
    return {
        "workspace_id": workspace_id,
        "workspaces": [{"id": row.id, "name": row.name, "role": row.role.value} for row in workspaces],
    }


class WorkspaceChoice(BaseModel):
    workspace_id: UUID


class AgentSetup(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    can_write: bool = False
    can_export: bool = False


@router.post("/dashboard/session")
def dashboard_login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    _require_dashboard()
    require_same_origin(request)
    login_result = login(body, db)
    response = JSONResponse(_session_info(db, login_result.user_id, login_result.workspace_id))
    set_session(request, response, db, login_result.user_id, login_result.workspace_id)
    response.delete_cookie("nk_dashboard_key")
    return response


def _dashboard_user(request: Request, db: Session = Depends(get_db)) -> Principal:
    _require_dashboard()
    origin = request.headers.get("origin")
    if origin and origin != public_origin(request):
        raise HTTPException(403, "Same-origin request required")
    principal = browser_principal(request, db)
    if not principal or not principal.user:
        raise HTTPException(401, "Sign in to Nakatomi")
    return principal


@router.get("/dashboard/session")
def dashboard_session(db: Session = Depends(get_db), p: Principal = Depends(_dashboard_user)):
    assert p.user is not None
    return JSONResponse(_session_info(db, p.user.id, p.workspace.id), headers={"Cache-Control": "no-store"})


@router.post("/dashboard/workspace")
def dashboard_workspace(
    body: WorkspaceChoice,
    request: Request,
    db: Session = Depends(get_db),
    p: Principal = Depends(_dashboard_user),
):
    require_same_origin(request)
    assert p.user is not None
    workspace_id = str(body.workspace_id)
    info = _session_info(db, p.user.id, workspace_id)
    if not any(item["id"] == workspace_id for item in info["workspaces"]):
        raise HTTPException(403, "Workspace membership required")
    response = JSONResponse(info)
    set_session(request, response, db, p.user.id, workspace_id)
    return response


@router.delete("/dashboard/session")
def dashboard_logout(request: Request, db: Session = Depends(get_db)):
    _require_dashboard()
    require_same_origin(request)
    response = Response(status_code=204)
    clear_session(request, response, db)
    return response


def _agent_records(db: Session, workspace_id: str):
    return db.scalars(
        select(ApiKey)
        .where(
            ApiKey.workspace_id == workspace_id,
            ApiKey.revoked_at.is_(None),
            or_(
                ApiKey.data["agent"].astext == "true",
                ApiKey.data["oauth"]["kind"].astext == "access",
                ApiKey.data["oauth"]["kind"].astext == "refresh",
            ),
        )
        .order_by(ApiKey.created_at.desc())
    )


def _agent_admin(p: Principal = Depends(_dashboard_user)) -> Principal:
    if p.role not in (MemberRole.owner, MemberRole.admin):
        raise HTTPException(403, "Workspace owner or admin required")
    return p


@router.get("/dashboard/agents")
def dashboard_agents(request: Request, db: Session = Depends(get_db), p: Principal = Depends(_agent_admin)):
    agents = {}
    client_names = {
        item.id: item.name
        for item in db.scalars(
            select(OAuthClient)
            .join(ApiKey, ApiKey.data["oauth"]["client_id"].astext == cast(OAuthClient.id, String))
            .where(ApiKey.workspace_id == p.workspace.id)
            .distinct()
        )
    }
    now = datetime.now(UTC)
    for key in _agent_records(db, p.workspace.id):
        grant = oauth_metadata(key)
        if key.expires_at and key.expires_at <= now and not grant:
            continue
        identity = grant.get("grant_id") or key.id
        record = agents.setdefault(
            identity,
            {
                "id": key.id,
                "name": client_names.get(grant.get("client_id"), key.name),
                "scopes": key.scopes,
                "last_used_at": key.last_used_at,
                "active": False,
            },
        )
        if key.expires_at is None or key.expires_at > now:
            record["active"] = True
        if grant.get("kind") == "access":
            record["scopes"] = key.scopes
        if key.last_used_at and (not record["last_used_at"] or key.last_used_at > record["last_used_at"]):
            record["last_used_at"] = key.last_used_at
    return {"url": f"{public_origin(request)}/mcp", "agents": [r for r in agents.values() if r["active"]]}


@router.post("/dashboard/agents", status_code=201)
def create_dashboard_agent(
    body: AgentSetup, request: Request, db: Session = Depends(get_db), p: Principal = Depends(_agent_admin)
):
    require_same_origin(request)
    token, prefix, digest = generate_api_key()
    scope = "mcp mcp:write" if body.can_write else "mcp"
    role = MemberRole.member if body.can_write else MemberRole.readonly
    scopes = oauth_scopes(f"{scope} mcp:export" if body.can_export else scope, role)
    key = ApiKey(
        workspace_id=p.workspace.id,
        name=body.name.strip() or "Agent",
        prefix=prefix,
        key_hash=digest,
        role=role,
        scopes=scopes,
        data={"agent": True, "allow_export": body.can_export},
    )
    db.add(key)
    db.commit()
    return JSONResponse(
        {"token": token, "url": f"{public_origin(request)}/mcp"},
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/dashboard/agents/{key_id}")
def disconnect_dashboard_agent(
    key_id: UUID, request: Request, db: Session = Depends(get_db), p: Principal = Depends(_agent_admin)
):
    require_same_origin(request)
    key = db.get(ApiKey, str(key_id))
    if (
        not key
        or key.workspace_id != p.workspace.id
        or not (oauth_metadata(key) or (key.data or {}).get("agent"))
    ):
        raise HTTPException(404, "Agent connection not found")
    revoke_grant(db, key)
    db.commit()
    return Response(status_code=204)
