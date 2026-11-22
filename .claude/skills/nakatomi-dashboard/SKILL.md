---
name: nakatomi-dashboard
description: Use this skill when the user wants to audit or visually inspect their Nakatomi CRM. Trigger on phrases like "nakatomi dashboard", "open my CRM", "show me the dashboard", "audit the CRM", "what's in my pipeline right now", "boot the dashboard". This skill launches a local Nakatomi instance if one isn't running, enables the dashboard, and opens Chrome at http://localhost:8000/dashboard.
---

# Nakatomi dashboard launcher

The dashboard shows workspace activity and lets workspace owners and admins manage agent connections. Sign in with your Nakatomi account.

## When this skill fires

1. Check whether Nakatomi is already running at `http://localhost:8000/health`.
2. If not, cd into the Nakatomi repo and:
   - If `docker-compose.yml` is present and Docker is running: `DASHBOARD_ENABLED=true docker compose up -d`
   - Otherwise: remind the user to run `./install.sh` or `pip install -r requirements.txt && DASHBOARD_ENABLED=true uvicorn app.main:app --reload`
3. Wait for `/health` to return 200 (up to 30 seconds; poll every 1s).
4. The dashboard is on by default. Sign in with a Nakatomi account and select a workspace when prompted.
5. Open Chrome at `http://localhost:8000/dashboard`.
   - macOS: `open -a "Google Chrome" http://localhost:8000/dashboard`
   - Linux: `google-chrome http://localhost:8000/dashboard` or `xdg-open`
   - Windows: `start chrome http://localhost:8000/dashboard`
6. Confirm to the user that the dashboard is up. It uses the same Nakatomi Plaza
   branding as welcome/OAuth (light panels, `/static/nakatomi-plaza-bg.jpg`).
   Point out the four views: **Audit** (timeline + entities + tasks), **Kanban**
   (pipeline board), **Webhooks** (delivery log), **Memory** (MemoryLink inspector).
   Full tour with screenshots: https://github.com/mrdulasolutions/NakatomiCRM/wiki/Dashboard

## Workspaces

Use the workspace picker to switch between workspaces you belong to. For a Railway deployment, open the dashboard on the configured HTTPS public origin.

## Typical follow-ups

After the dashboard is open, the user often asks for:

- "Show me today's activity" → filter timeline by `since=<today 00:00>`
- "What deals closed this week?" → filter timeline by `event_type=deal.won`
- "Any failing webhooks?" → navigate to `/dashboard/webhooks`

Each of those is also available via the REST API; offer to use the API
instead if the user prefers a text-based summary.
