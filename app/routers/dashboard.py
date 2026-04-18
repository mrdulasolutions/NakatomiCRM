"""Local audit dashboard. Off by default. Enable with DASHBOARD_ENABLED=true.

This is NOT a rich product UI. It's a minimal HTML page that fetches the REST
API and shows a read-only view of recent activity, contacts, companies, deals,
and webhook deliveries.

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
    header { padding: 16px 20px; border-bottom: 1px solid #20242a; display: flex; gap: 12px; align-items: center; }
    header h1 { margin: 0; font-size: 14px; letter-spacing: 2px; text-transform: uppercase; color: #6cf; }
    header span { opacity: 0.6; font-size: 12px; }
    main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px; }
    section { background: #11151a; border: 1px solid #20242a; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; max-height: 80vh; }
    section h2 { margin: 0; padding: 10px 14px; font-size: 12px; letter-spacing: 1px; text-transform: uppercase; background: #161b21; border-bottom: 1px solid #20242a; color: #9ab; }
    section .body { padding: 8px 14px; overflow: auto; font-size: 12px; line-height: 1.55; }
    .row { padding: 6px 0; border-bottom: 1px dashed #20242a; }
    .row:last-child { border-bottom: none; }
    .row .k { color: #6cf; }
    .row .t { color: #7a8590; font-size: 11px; }
    .auth { padding: 18px; max-width: 420px; margin: 64px auto; background: #11151a; border: 1px solid #20242a; border-radius: 8px; }
    input, button { font: inherit; padding: 8px 10px; background: #0b0d10; color: #e6e8ea; border: 1px solid #20242a; border-radius: 6px; width: 100%; margin-top: 8px; box-sizing: border-box; }
    button { cursor: pointer; }
    .empty { opacity: 0.5; padding: 12px 0; }
  </style>
</head>
<body>
<header>
  <h1>Nakatomi · audit</h1>
  <span id="ws"></span>
  <span style="flex:1"></span>
  <button id="logout" style="width:auto;padding:4px 10px;font-size:11px">logout</button>
</header>
<div id="auth" class="auth" hidden>
  <h2 style="margin:0 0 12px 0">enter your API key</h2>
  <input id="key" type="password" placeholder="nk_..." autocomplete="off" />
  <button id="save">use key</button>
  <p style="opacity:.6;font-size:12px">Stored in a cookie so you don't have to paste it every time. Clear with logout.</p>
</div>
<main id="app" hidden>
  <section><h2>timeline</h2><div class="body" id="timeline"></div></section>
  <section><h2>recent contacts</h2><div class="body" id="contacts"></div></section>
  <section><h2>recent companies</h2><div class="body" id="companies"></div></section>
  <section><h2>deals</h2><div class="body" id="deals"></div></section>
  <section><h2>open tasks</h2><div class="body" id="tasks"></div></section>
  <section><h2>webhook deliveries</h2><div class="body" id="webhooks"></div></section>
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

async function load() {
  try {
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
    d.items.forEach(x => dEl.appendChild(row(x.name, `${x.status} · $${x.amount||0} ${x.currency}`, x.updated_at)));

    const t = await api("/tasks?status=open&limit=20");
    const tEl = document.getElementById("tasks"); tEl.innerHTML = "";
    if (!t.items.length) tEl.appendChild(empty());
    t.items.forEach(x => tEl.appendChild(row(x.title, x.due_at ? `due ${x.due_at}` : "", x.created_at)));

    const wh = await api("/webhooks");
    const whEl = document.getElementById("webhooks"); whEl.innerHTML = "";
    if (!wh.length) whEl.appendChild(empty());
    wh.forEach(x => whEl.appendChild(row(x.name, `${x.url} · failures=${x.failure_count}`, x.last_delivery_at || "(never fired)")));
  } catch (e) {
    console.error(e);
    clearKey();
  }
}

(function init() {
  if (getKey()) {
    document.getElementById("app").hidden = false;
    load();
  } else {
    document.getElementById("auth").hidden = false;
  }
  document.getElementById("save").onclick = () => {
    const k = document.getElementById("key").value.trim();
    if (!k.startsWith("nk_")) { alert("expected an nk_... key"); return; }
    setKey(k); location.reload();
  };
  document.getElementById("logout").onclick = clearKey;
})();
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
