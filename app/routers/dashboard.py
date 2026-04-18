"""Local audit dashboard. Off by default. Enable with DASHBOARD_ENABLED=true.

This is NOT a rich product UI. It's a minimal HTML page that fetches the REST
API and shows a read-only view of activity, pipelines, and webhook state.

Binding: we do not restrict the bind host here (that's a deployment concern).
The skill that launches this via docker compose sets up a local-only binding.
For Railway/prod, gate it behind your own reverse proxy — the dashboard
expects a workspace API key in a cookie named ``nk_dashboard_key``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(tags=["dashboard"])


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Nakatomi · dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root { color-scheme: dark; }
    body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0; background: #0b0d10; color: #e6e8ea; }
    header { padding: 14px 20px; border-bottom: 1px solid #20242a; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
    header h1 { margin: 0; font-size: 14px; letter-spacing: 2px; text-transform: uppercase; color: #6cf; }
    header span { opacity: 0.6; font-size: 12px; }
    nav { display: flex; gap: 4px; }
    nav button { font: inherit; padding: 4px 12px; font-size: 11px; background: transparent; color: #9ab; border: 1px solid #20242a; border-radius: 6px; cursor: pointer; }
    nav button.active { background: #11151a; color: #6cf; border-color: #2d3540; }
    main { padding: 16px; }
    .view { display: none; }
    .view.active { display: block; }

    /* audit grid */
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    section { background: #11151a; border: 1px solid #20242a; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; max-height: 80vh; }
    section h2 { margin: 0; padding: 10px 14px; font-size: 12px; letter-spacing: 1px; text-transform: uppercase; background: #161b21; border-bottom: 1px solid #20242a; color: #9ab; }
    section .body { padding: 8px 14px; overflow: auto; font-size: 12px; line-height: 1.55; }
    .row { padding: 6px 0; border-bottom: 1px dashed #20242a; }
    .row:last-child { border-bottom: none; }
    .row .k { color: #6cf; }
    .row .t { color: #7a8590; font-size: 11px; }

    /* kanban */
    .pipe-label { padding: 8px 4px; color: #9ab; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; }
    .kanban { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(240px, 1fr); gap: 12px; overflow-x: auto; padding-bottom: 8px; }
    .col { background: #11151a; border: 1px solid #20242a; border-radius: 8px; display: flex; flex-direction: column; max-height: 75vh; }
    .col h3 { margin: 0; padding: 10px 14px; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; color: #9ab; background: #161b21; border-bottom: 1px solid #20242a; display: flex; justify-content: space-between; }
    .col h3 .won { color: #7ee787; }
    .col h3 .lost { color: #ff8b8b; }
    .col h3 .count { color: #6cf; font-weight: normal; }
    .col .stack { padding: 8px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
    .card { background: #0e1216; border: 1px solid #20242a; border-radius: 6px; padding: 10px; font-size: 12px; }
    .card .name { color: #e6e8ea; font-weight: 600; margin-bottom: 4px; overflow-wrap: anywhere; }
    .card .meta { color: #9ab; font-size: 11px; }
    .card .amt { color: #7ee787; font-size: 11px; }
    .col-total { color: #6cf; font-size: 11px; }

    /* webhooks view */
    .wh-item { background: #11151a; border: 1px solid #20242a; border-radius: 8px; margin-bottom: 10px; overflow: hidden; }
    .wh-head { padding: 10px 14px; cursor: pointer; display: flex; gap: 12px; align-items: center; }
    .wh-head:hover { background: #161b21; }
    .wh-name { color: #6cf; font-size: 13px; font-weight: 600; }
    .wh-url { color: #9ab; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
    .wh-badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; border: 1px solid #20242a; color: #9ab; letter-spacing: 0.5px; text-transform: uppercase; }
    .wh-badge.fail { color: #ff8b8b; border-color: #4a2830; }
    .wh-badge.ok   { color: #7ee787; border-color: #224432; }
    .wh-badge.off  { color: #7a8590; border-color: #2a313a; }
    .wh-body { border-top: 1px solid #20242a; padding: 10px 14px; background: #0e1216; }
    .wh-delivery { padding: 8px 0; border-bottom: 1px dashed #20242a; font-size: 11px; line-height: 1.5; }
    .wh-delivery:last-child { border-bottom: none; }
    .wh-delivery .status { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; letter-spacing: 0.5px; text-transform: uppercase; margin-right: 6px; }
    .wh-delivery .status.succeeded { background: #122a1a; color: #7ee787; }
    .wh-delivery .status.dead      { background: #2a1212; color: #ff8b8b; }
    .wh-delivery .status.pending   { background: #1a1a2a; color: #c8a8ff; }
    .wh-delivery .event { color: #6cf; }
    .wh-delivery .meta { color: #7a8590; }
    .wh-delivery pre { margin: 4px 0 0 0; padding: 6px 8px; background: #0b0d10; border: 1px solid #20242a; border-radius: 4px; font-size: 10px; color: #e6e8ea; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 200px; overflow: auto; }

    /* auth */
    .auth { padding: 18px; max-width: 420px; margin: 64px auto; background: #11151a; border: 1px solid #20242a; border-radius: 8px; }
    input, button#save { font: inherit; padding: 8px 10px; background: #0b0d10; color: #e6e8ea; border: 1px solid #20242a; border-radius: 6px; width: 100%; margin-top: 8px; box-sizing: border-box; }
    button#save { cursor: pointer; }
    .empty { opacity: 0.5; padding: 12px 0; }
  </style>
</head>
<body>
<header>
  <h1>Nakatomi</h1>
  <span id="ws"></span>
  <nav>
    <button data-view="audit" class="active">Audit</button>
    <button data-view="kanban">Kanban</button>
    <button data-view="webhooks">Webhooks</button>
  </nav>
  <span style="flex:1"></span>
  <button id="logout" style="padding:4px 10px;font-size:11px;background:transparent;color:#9ab;border:1px solid #20242a;border-radius:6px;cursor:pointer">logout</button>
</header>

<div id="auth" class="auth" hidden>
  <h2 style="margin:0 0 12px 0">enter your API key</h2>
  <input id="key" type="password" placeholder="nk_..." autocomplete="off" />
  <button id="save">use key</button>
  <p style="opacity:.6;font-size:12px">Stored in a cookie so you don't have to paste it every time. Clear with logout.</p>
</div>

<main id="app" hidden>
  <div id="view-audit" class="view active">
    <div class="grid">
      <section><h2>timeline</h2><div class="body" id="timeline"></div></section>
      <section><h2>recent contacts</h2><div class="body" id="contacts"></div></section>
      <section><h2>recent companies</h2><div class="body" id="companies"></div></section>
      <section><h2>deals</h2><div class="body" id="deals"></div></section>
      <section><h2>open tasks</h2><div class="body" id="tasks"></div></section>
      <section><h2>webhook deliveries</h2><div class="body" id="webhooks"></div></section>
    </div>
  </div>
  <div id="view-kanban" class="view">
    <div id="pipe-label" class="pipe-label">pipeline:</div>
    <div class="kanban" id="kanban"></div>
  </div>
  <div id="view-webhooks" class="view">
    <div id="wh-controls" style="padding:8px 4px;color:#9ab;font-size:11px;display:flex;gap:12px;align-items:center">
      <span>status filter:</span>
      <select id="wh-filter" style="padding:4px 8px;background:#0b0d10;color:#e6e8ea;border:1px solid #20242a;border-radius:6px;font:inherit">
        <option value="">all</option>
        <option value="pending">pending</option>
        <option value="succeeded">succeeded</option>
        <option value="dead">dead</option>
      </select>
      <span style="flex:1"></span>
      <button id="wh-refresh" style="padding:4px 10px;font-size:11px;background:transparent;color:#9ab;border:1px solid #20242a;border-radius:6px;cursor:pointer">refresh</button>
    </div>
    <div id="wh-root"></div>
  </div>
</main>

<script>
const COOKIE = "nk_dashboard_key";
function getKey() {
  const m = document.cookie.match(/(?:^|; )nk_dashboard_key=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}
function setKey(k) {
  document.cookie = `${COOKIE}=${encodeURIComponent(k)};path=/dashboard;SameSite=Strict;max-age=2592000`;
}
function clearKey() { document.cookie = `${COOKIE}=;path=/dashboard;max-age=0`; location.reload(); }

async function api(path) {
  const key = getKey(); if (!key) throw new Error("no key");
  const r = await fetch(path, { headers: { Authorization: `Bearer ${key}` } });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}
function row(key, text, time) {
  const d = document.createElement("div"); d.className = "row";
  d.innerHTML = `<span class="k">${key}</span> ${text} ${time ? `<div class="t">${time}</div>` : ""}`;
  return d;
}
function empty() { const d = document.createElement("div"); d.className = "empty"; d.textContent = "— nothing yet —"; return d; }

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
      <span class="meta" style="color:#7a8590;font-size:11px">${hook.last_delivery_at ? "last: " + new Date(hook.last_delivery_at).toLocaleString() : "never fired"}</span>
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
            if (d.error) parts.push(`<div class="meta" style="color:#ff8b8b">error: ${esc(d.error)}</div>`);
            if (d.response_body) parts.push(`<pre>${esc(d.response_body.slice(0, 400))}</pre>`);
            row.innerHTML = parts.join("");
            body.appendChild(row);
          }
        } catch (err) {
          body.innerHTML = `<div class="meta" style="color:#ff8b8b">failed: ${esc(err.message)}</div>`;
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

function switchView(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("active", b.dataset.view === name);
  for (const v of document.querySelectorAll(".view")) v.classList.toggle("active", v.id === "view-" + name);
  if (name === "kanban") loadKanban().catch(err => { console.error(err); clearKey(); });
  if (name === "webhooks") loadWebhooks().catch(err => { console.error(err); clearKey(); });
}

async function init() {
  if (!getKey()) { document.getElementById("auth").hidden = false; return; }
  document.getElementById("app").hidden = false;
  try { await loadAudit(); } catch (e) { console.error(e); clearKey(); return; }
  for (const b of document.querySelectorAll("nav button")) b.addEventListener("click", () => switchView(b.dataset.view));
  document.getElementById("wh-refresh").addEventListener("click", () => loadWebhooks());
  document.getElementById("wh-filter").addEventListener("change", () => loadWebhooks());
}

document.getElementById("save").onclick = () => {
  const k = document.getElementById("key").value.trim();
  if (!k.startsWith("nk_")) { alert("expected an nk_... key"); return; }
  setKey(k); location.reload();
};
document.getElementById("logout").onclick = clearKey;

init();
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    if not settings.DASHBOARD_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="dashboard disabled; set DASHBOARD_ENABLED=true and restart",
        )
    return HTMLResponse(_DASHBOARD_HTML)
