# Optional SSO (Google / GitHub)

Human-operator login via OAuth. **Agents should keep using API keys or
MCP OAuth** — SSO is for people (dashboard, bootstrap, admin JWT).

## Enable

```env
PUBLIC_BASE_URL=https://crm.example.com   # used in redirect_uri

# Google Cloud OAuth client (Web application)
SSO_GOOGLE_CLIENT_ID=....apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=...

# GitHub OAuth App
SSO_GITHUB_CLIENT_ID=...
SSO_GITHUB_CLIENT_SECRET=...

# First login creates a personal workspace if the user has none (default true)
SSO_AUTO_CREATE_WORKSPACE=true
```

Redirect URIs to register with the IdP:

- `https://crm.example.com/auth/sso/google/callback`
- `https://crm.example.com/auth/sso/github/callback`

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/auth/sso/providers` | Which providers are configured |
| `GET` | `/auth/sso/{google\|github}` | 302 to IdP |
| `GET` | `/auth/sso/{provider}/callback` | Issues JWT (`TokenResponse`) |

## Behaviour

1. Existing user matched by `(sso_provider, sso_subject)` → login.
2. Else existing user matched by **email** → link SSO fields, login.
3. Else create user with `password_hash=null` (SSO-only).
4. If no membership and `SSO_AUTO_CREATE_WORKSPACE=true`, create a
   personal workspace as owner.
5. Password login rejects SSO-only accounts (no local password).

## Security notes

- State parameter is a short-lived signed JWT (HS256 with `SECRET_KEY`).
- Production refuses to boot with a default/short `SECRET_KEY`
  (`ENVIRONMENT=production`).
- Scope: Google `openid email profile`; GitHub `read:user user:email`.
