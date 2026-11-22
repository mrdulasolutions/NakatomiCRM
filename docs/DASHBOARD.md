# Audit dashboard

Use **`/dashboard`** to inspect workspace activity, manage team membership, and connect agents. The hosted instance is available at the [Railway dashboard](https://nakatomi-production-3c7aa7a7.up.railway.app/dashboard).

**Wiki (screenshots + tour):** [GitHub Wiki — Dashboard](https://github.com/mrdulasolutions/NakatomiCRM/wiki/Dashboard)

---

## Sign in

Open **`/dashboard`** and sign in with your Nakatomi email and password or a configured Google or GitHub provider. Select a workspace if you belong to more than one. The server stores your session and invalidates it when you sign out. The dashboard is enabled by default. Set `DASHBOARD_ENABLED=false` to disable it.

For Railway, configure `ENVIRONMENT=production` and a strong `SECRET_KEY`. Set `PUBLIC_BASE_URL` to your canonical HTTPS origin when using a custom domain. The app otherwise uses the Railway service domain. Use that same origin for the provider callback URLs.

## Share a workspace with your team

Each teammate signs in with their own account. Members of the same workspace
share its CRM records, including contacts, companies, deals, and tasks.

1. Sign in as a workspace owner or admin, select the company workspace, and
   open **Members**.
2. Enter your teammate’s email and choose **Member** or **Read-only**. Owners
   can also invite **Admins**. Select **Create invitation**.
3. Your teammate opens the invitation and joins the workspace. New users set a
   password and join the company workspace directly. Existing users can use
   their current password or an active session for the invited email. Existing
   Google or GitHub users can sign in first and then reopen the invitation.
4. After accepting, the dashboard opens in the company workspace. Teammates
   with multiple memberships can move between them using the **Workspace** menu.

Invitations expire after two days and work once. To resend, create another
invitation for the same email. That invalidates the previous link. You can
also revoke a pending invitation from **Members**. Use the same page to
change teammates’ roles or remove their workspace access. Owners manage
admins, and both owners and admins manage members and read-only teammates.

### Invitation delivery

Invitations and password recovery use the same installation-wide mail settings.
For Resend, set `RECOVERY_RESEND_API_KEY` and `RECOVERY_FROM_ADDRESS` using a
verified sender. If you have already configured Resend for password recovery,
those settings also enable invitation email. SMTP is also supported. If mail
is unconfigured or sending fails, copy the generated invitation link from the
dashboard and share it privately with the intended teammate.

On Railway, links use the service’s public domain unless you set
`PUBLIC_BASE_URL` for a custom domain. Use Resend on Railway plans that block
outbound SMTP. On a VPS or Docker Compose deployment, set `PUBLIC_BASE_URL`
to the HTTPS address teammates use. On a local-only install, use your
loopback address, such as `http://localhost:8000`. A loopback link can only be
opened on the machine running Nakatomi. To invite teammates on other machines,
use a reachable HTTPS origin.

The API still supports listing members with `GET /workspace/members`, adding
an existing account with `POST /workspace/members`, and removing a member
with `DELETE /workspace/members/{user_id}`.

## Password recovery

Use **Forgot password?** on the dashboard or the MCP authorization page.
Password-based accounts can request a single-use link valid for 20 minutes
after the operator configures recovery email. SSO-only users recover access
through their identity provider.

Set `RECOVERY_FROM_ADDRESS` to a sender approved by your mail provider.
Set `RECOVERY_RESEND_API_KEY` to deliver over HTTPS through Resend. This option
works on Railway plans that block outbound SMTP and takes precedence when configured.
For SMTP delivery, configure `RECOVERY_SMTP_HOST`,
`RECOVERY_SMTP_PORT`, `RECOVERY_FROM_ADDRESS`, and the SMTP username and
password when required. Port 587 uses STARTTLS by default and port 465 uses
implicit TLS. For a local test mail relay, explicitly allow its hostname in
`INTEGRATION_PRIVATE_HOSTS` and set `RECOVERY_SMTP_USE_TLS=false` if needed.

| Deployment | Recovery link origin | Operator reset |
| --- | --- | --- |
| Railway | Uses the Railway public domain. Set `PUBLIC_BASE_URL` for a custom domain. | In the app service's Railway SSH terminal, run `python -m app reset-password --email owner@example.com`. |
| VPS | Set `PUBLIC_BASE_URL` to the public HTTPS origin. | Run the same command in the app environment, or prefix it with `docker compose exec app`. |
| Local | Set `PUBLIC_BASE_URL=http://localhost:8000` or your actual loopback URL. | Run the same command in the local Python environment, or prefix it with `docker compose exec app`. |

The operator command works without a mail provider and prompts for the password without
echoing it. Use the database for the existing installation. Both recovery
paths preserve the account and workspace memberships and revoke browser
sessions. Existing API keys and agent grants retain their own revocation
controls. Run Alembic migration 0019 before using the flow.

## Views

| Tab | Purpose |
| --- | --- |
| **Audit** | Timeline + recent contacts/companies/deals + open tasks + webhook strip |
| **Kanban** | Read-only pipeline board (up to 4k deals) |
| **Webhooks** | Subscribers + expandable delivery log |
| **Memory** | `MemoryLink` inspector + connector env banner |

### Screenshots

Same assets as the wiki (`docs/assets/dashboard/`):

| Audit | Kanban |
| --- | --- |
| ![Audit dashboard](./assets/dashboard/dashboard-audit.png) | ![Kanban pipeline](./assets/dashboard/dashboard-kanban.jpg) |

| Webhooks | Memory |
| --- | --- |
| ![Webhooks tab](./assets/dashboard/dashboard-webhooks.jpg) | ![Memory links — Supermemory handoff](./assets/dashboard/dashboard-memory.jpg) |

The Memory tab distinguishes **`MEMORY_CONNECTORS`** (server adapters) from **link rows** created via MCP `memory_link` or REST — see [MEMORY.md](./MEMORY.md).

---

## Connect an agent

Workspace owners and admins can open **Connect an agent** to copy the MCP URL, issue a dedicated headless credential, test a read-only tool, and disconnect credentials. Read-only is the default. Select **Allow CRM writes** when the bot needs to modify records.

- **Grok API and headless DOTs:** point the runtime at the displayed HTTPS `/mcp` URL. Store the credential in the runtime’s secret store and pass it as MCP authorization. Displayed credentials can be copied once.
- **Interactive DOTs and MCP clients:** use the same URL and approve the workspace and scopes in the browser. `mcp` grants reads and `mcp:write` requests CRM writes. Clients refresh delegated tokens with their registered client ID.
- **Multiple Railway replicas:** validate your clients with `MCP_STATELESS_HTTP=true` before scaling so requests do not depend on in-memory session affinity.

Existing OAuth access tokens with legacy wildcard permissions are retired during upgrade. Clients that have a valid refresh token and their registered client ID can renew. Reconnect clients that cannot refresh. Workspace API keys issued outside OAuth continue to work.

See [SSO setup](SSO.md) for provider callbacks.

## Export a workspace through an agent

Ask a connected agent to **export this workspace as a ZIP for Railway**, a VPS,
or local use. The agent calls `export_workspace_zip` and returns a browser
download link valid for 10 minutes. Share that link only with the intended
recipient. The download is generated from the current workspace when opened.

The workspace ZIP is intended for import into an existing installation. It includes the portable workspace JSON, a manifest, and restore
instructions for the selected target. Ask to include attachments or timeline
history if you need them. An owner or admin can enable **Allow workspace ZIP exports** when creating a
headless agent credential. Interactive OAuth agents must request `mcp:export` and receive owner or admin
approval. Attachment bytes also require `files:read`.
