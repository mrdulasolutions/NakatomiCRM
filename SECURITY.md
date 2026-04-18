# Security Policy

## Supported versions

Nakatomi is pre-1.0. The latest tagged release on `main` is the supported version.
Once we cut v1.0, this section will list a supported range.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Email **security@nakatomi.dev** (or, for now while we're pre-release, open a
GitHub Security Advisory: *Security → Report a vulnerability*). Include:

- A description of the issue and its impact
- Steps to reproduce, ideally with a minimal proof of concept
- Any mitigation you're already applying
- Whether you'd like credit; and if so, the name/handle to credit

We aim to:

- Acknowledge the report within **3 business days**
- Provide a triage assessment within **10 business days**
- Ship a fix or mitigation within **30 days** for high-severity issues, faster
  where possible

We will coordinate disclosure with you. If you've been waiting longer than the
targets above, please nudge us.

## Scope

In scope:
- Authentication / authorization bypass (API key scoping, workspace isolation)
- SQL injection, XSS, SSRF in any Nakatomi-served endpoint or the local dashboard
- Webhook signing bypass or replay
- File upload / storage abuse
- Memory connector adapter bugs that leak data across tenants

Out of scope (please don't report):
- Rate-limit gaps on endpoints we have not yet rate-limited (known gap — see
  roadmap)
- Attacks requiring a malicious *authenticated* admin of the same workspace
- DoS by high-volume request floods

## Dependency handling

We use pinned versions in `requirements.txt`. If you find a vulnerability in a
dependency that's exploitable through Nakatomi, please still report it — we'll
pull/pin the upstream fix.

## Secrets hygiene

- Never commit an `.env` file. The repo ships `.env.example` only.
- API keys are stored as SHA-256 hashes. The plaintext is shown exactly once at
  creation time.
- Webhook secrets are generated server-side and returned once at creation time.
- Workspace members can rotate keys at any time by revoking the old one and
  minting a new one.
