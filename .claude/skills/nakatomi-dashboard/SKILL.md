---
name: nakatomi-dashboard
description: Use this skill when the user wants to audit or visually inspect their Nakatomi CRM. Trigger on phrases like "nakatomi dashboard", "open my CRM", "show me the dashboard", "audit the CRM", "what's in my pipeline right now", "boot the dashboard". This skill launches a local Nakatomi instance if one isn't running, enables the dashboard, and opens Chrome at http://localhost:8000/dashboard.
---

# Nakatomi dashboard launcher

Nakatomi's dashboard is **audit-only** — it's for a human to glance at what the
agents did, not for heavy data entry. It's disabled by default because most
users run Nakatomi remotely on Railway; turning the dashboard on makes sense
for local review.

## When this skill fires

1. Check whether Nakatomi is already running at `http://localhost:8000/health`.
2. If not, cd into the Nakatomi repo and:
   - If `docker-compose.yml` is present and Docker is running: `DASHBOARD_ENABLED=true docker compose up -d`
   - Otherwise: remind the user to run `./install.sh` or `pip install -r requirements.txt && DASHBOARD_ENABLED=true uvicorn app.main:app --reload`
3. Wait for `/health` to return 200 (up to 30 seconds; poll every 1s).
4. Ensure the dashboard is enabled (the env var was set above). If not, instruct the user to set `DASHBOARD_ENABLED=true` and restart.
5. Open Chrome at `http://localhost:8000/dashboard`.
   - macOS: `open -a "Google Chrome" http://localhost:8000/dashboard`
   - Linux: `google-chrome http://localhost:8000/dashboard` or `xdg-open`
   - Windows: `start chrome http://localhost:8000/dashboard`
6. Confirm to the user that the dashboard is up and point out the views:
   timeline stream, recent contacts/companies/deals, webhook delivery log.

## Safety

- The dashboard binds to `127.0.0.1` by default. Do NOT expose it on a public
  interface. If a user asks to make it reachable from another machine, refuse
  and explain that the dashboard has minimal auth — they should use the REST
  API with proper auth instead.
- If there are multiple Nakatomi workspaces locally, the dashboard reads from
  the one configured by the loaded `.env`. Mention this if there's any chance
  of confusion.

## Typical follow-ups

After the dashboard is open, the user often asks for:

- "Show me today's activity" → filter timeline by `since=<today 00:00>`
- "What deals closed this week?" → filter timeline by `event_type=deal.won`
- "Any failing webhooks?" → navigate to `/dashboard/webhooks`

Each of those is also available via the REST API; offer to use the API
instead if the user prefers a text-based summary.
