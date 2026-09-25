"""Local audit dashboard. Off by default. Enable with DASHBOARD_ENABLED=true.

This is NOT a rich product UI. It's a minimal HTML page that fetches the REST
API and shows a read-only view of activity, pipelines, and webhook state.

Binding: we do not restrict the bind host here (that's a deployment concern).
The skill that launches this via docker compose sets up a local-only binding.
For Railway/prod, gate it behind your own reverse proxy — the dashboard
expects a workspace API key in a cookie named ``nk_dashboard_key``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.brand_pages import dashboard_stylesheet, render_dashboard_disabled
from app.config import settings

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
  </nav>
  <span style="flex:1"></span>
  <button type="button" id="logout" class="dash-btn-ghost">Sign out</button>
</header>

<div id="auth-wrap" class="dash-auth-wrap" hidden>
  <div id="auth" class="dash-auth">
    <p class="mark">Nakatomi CRM</p>
    <h2>Connect your API key</h2>
    <p class="lede">Read-only view of timeline, pipelines, webhooks, and memory links. Paste a workspace key with list scopes.</p>
    <label for="key">API key</label>
    <input id="key" type="password" placeholder="nk_..." autocomplete="off" />
    <div id="auth-error" class="alert err" hidden role="alert"></div>
    <button type="button" id="save">Use key</button>
    <p class="foot">Stored in a cookie on this path only. Sign out clears it.</p>
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
      <button type="button" id="wh-refresh" class="dash-btn-ghost">Refresh</button>
    </div>
    <div id="wh-root"></div>
  </div>
  <div id="view-memory" class="dash-view">
    <div class="dash-toolbar">
      <span>Connectors</span>
      <span id="mem-connectors" class="accent">—</span>
      <span style="flex:1"></span>
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
</main>
</div>

<script>
const COOKIE = "nk_dashboard_key";
const STORAGE_KEY = "nk_dashboard_key";

function getKey() {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
  } catch (e) { /* private mode */ }
  const m = document.cookie.match(/(?:^|; )nk_dashboard_key=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}
function setKey(k) {
  try { sessionStorage.setItem(STORAGE_KEY, k); } catch (e) { /* ignore */ }
  const secure = location.protocol === "https:" ? ";Secure" : "";
  document.cookie = `${COOKIE}=${encodeURIComponent(k)};path=/;SameSite=Lax;max-age=2592000${secure}`;
}
function clearKey() {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  document.cookie = `${COOKIE}=;path=/;max-age=0`;
  location.reload();
}

function showAuthError(msg) {
  setDashboardAuth(true);
  const err = document.getElementById("auth-error");
  err.hidden = false;
  err.textContent = msg;
}

function setDashboardAuth(showLogin) {
  document.querySelector(".dash-shell").classList.toggle("dash-authed", !showLogin);
  document.getElementById("auth-wrap").hidden = showLogin;
  document.getElementById("app").hidden = showLogin;
}

async function api(path) {
  const key = getKey();
  if (!key) throw new Error("No API key saved");
  const r = await fetch(path, { headers: { Authorization: `Bearer ${key}` } });
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
function row(key, text, time) {
  const d = document.createElement("div"); d.className = "dash-row";
  d.innerHTML = `<span class="k">${key}</span> ${text} ${time ? `<div class="t">${time}</div>` : ""}`;
  return d;
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
    const name = stage.is_won ? `<span class="won">${esc(stage.name)}</span>`
               : stage.is_lost ? `<span class="lost">${esc(stage.name)}</span>`
               : esc(stage.name);
    const items = byStage.get(stage.id) || [];
    const total = items.reduce((acc, d) => acc + Number(d.amount || 0), 0);
    h3.innerHTML = `${name} <span class="count">${items.length}${total ? ` · ${fmtMoney(total, items[0]?.currency || "USD")}` : ""}</span>`;
    col.appendChild(h3);
    const stack = document.createElement("div"); stack.className = "stack";
    if (!items.length) {
      const e = document.createElement("div"); e.className = "empty"; e.textContent = "—"; stack.appendChild(e);
    }
    for (const d of items) {
      const card = document.createElement("div"); card.className = "card";
      const close = d.expected_close_date ? ` · close ${new Date(d.expected_close_date).toLocaleDateString()}` : "";
      card.innerHTML = `
        <div class="name">${esc(d.name)}</div>
        <div class="amt">${fmtMoney(d.amount, d.currency)}</div>
        <div class="meta">${esc(d.status)}${close}</div>
      `;
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
      <span class="wh-badge ${badgeClass}">${badgeText}</span>
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
            const parts = [`<span class="status ${status}">${status}</span>`];
            parts.push(`<span class="event">${esc(d.event_type)}</span>`);
            parts.push(`<span class="meta"> · attempt ${d.attempts}`);
            if (d.status_code != null) parts.push(` · http ${d.status_code}`);
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
let _memFirstLoad = true;

async function loadMemory(reset = true) {
  if (reset) _memCursor = null;
  const connector = document.getElementById("mem-connector-filter").value;
  const entityType = document.getElementById("mem-entity-filter").value;

  // Populate connectors list + filter options on first open.
  if (_memFirstLoad) {
    try {
      const conns = await api("/memory/connectors");
      const el = document.getElementById("mem-connectors");
      el.textContent = conns.length ? conns.join(", ") : "none enabled";
      const sel = document.getElementById("mem-connector-filter");
      for (const c of conns) {
        const opt = document.createElement("option"); opt.value = c; opt.textContent = c; sel.appendChild(opt);
      }
    } catch (e) { /* non-fatal */ }
    _memFirstLoad = false;
  }

  const qs = new URLSearchParams({ limit: "50" });
  if (connector) qs.set("connector", connector);
  if (entityType) qs.set("entity_type", entityType);
  if (_memCursor) qs.set("cursor", _memCursor);

  const page = await api(`/memory/links?${qs}`);
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
      <span class="ref">→ <span class="mono">${shortEid}</span> · external: <span class="mono">${esc(shortExt)}</span></span>
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

async function init() {
  if (!getKey()) {
    setDashboardAuth(true);
    return;
  }
  setDashboardAuth(false);
  document.getElementById("auth-error").hidden = true;
  try {
    await loadAudit();
  } catch (e) {
    console.error(e);
    const status = e.status || 0;
    if (status === 401) {
      try { sessionStorage.removeItem(STORAGE_KEY); } catch (x) { /* ignore */ }
      document.cookie = `${COOKIE}=;path=/;max-age=0`;
    }
    showAuthError(
      status === 403
        ? `${e.message} — use a key with * or read scopes for timeline, contacts, deals, tasks, webhooks.`
        : e.message || "Could not load dashboard data."
    );
    return;
  }
  wireUi();
}

document.getElementById("save").onclick = async () => {
  const k = document.getElementById("key").value.trim();
  if (!k.startsWith("nk_")) { alert("Expected an nk_… API key"); return; }
  document.getElementById("auth-error").hidden = true;
  setKey(k);
  await init();
};
document.getElementById("logout").onclick = clearKey;

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
    return HTMLResponse(_DASHBOARD_HTML)
