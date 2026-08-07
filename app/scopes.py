"""Capability scopes for API keys (and role-derived JWT principals).

Scopes are coarse, agent-friendly permissions. Format: ``resource:action``.

Special values:
- ``*`` — full access (owner keys)
- ``*:read`` — every ``*:read`` scope
- ``*:write`` — every ``*:write`` scope (not delete/send/admin)

Legacy keys with ``scopes is None`` or empty list are treated as ``["*"]`` so
existing deployments keep working after the migration.
"""

from __future__ import annotations

from app.models import MemberRole

# Resources that participate in the CRM surface.
RESOURCES: tuple[str, ...] = (
    "contacts",
    "companies",
    "deals",
    "products",
    "pipelines",
    "activities",
    "notes",
    "tasks",
    "files",
    "relationships",
    "timeline",
    "webhooks",
    "memory",
    "ingest",
    "forecast",
    "custom_fields",
    "export",
    "email",
    "calendar",
    "approvals",
    "workspace",
    "leads",
    "quotes",
    "views",
    "jobs",
)

ACTIONS: tuple[str, ...] = ("read", "write", "delete")

# Standalone capabilities (not resource:action).
SPECIAL: tuple[str, ...] = (
    "email:send",
    "admin:keys",
    "a2a:invoke",
    "a2a:admin",
)


def all_read_scopes() -> list[str]:
    return [f"{r}:read" for r in RESOURCES]


def all_write_scopes() -> list[str]:
    return [f"{r}:write" for r in RESOURCES]


def all_delete_scopes() -> list[str]:
    return [f"{r}:delete" for r in RESOURCES]


def all_known_scopes() -> list[str]:
    return sorted(
        {
            *all_read_scopes(),
            *all_write_scopes(),
            *all_delete_scopes(),
            *SPECIAL,
            "*",
            "*:read",
            "*:write",
        }
    )


# Default for new member/agent keys: write CRM data, no hard-delete, no email
# send, no key admin. Soft-delete uses :write on most routers today.
DEFAULT_AGENT_SCOPES: list[str] = sorted(
    {
        *all_read_scopes(),
        *all_write_scopes(),
        "approvals:read",
        "approvals:write",
        "a2a:invoke",
        # deliberately omitted: email:send, admin:keys, *:delete, a2a:admin
    }
)

READONLY_SCOPES: list[str] = sorted({*all_read_scopes(), "approvals:read", "a2a:invoke"})

FULL_SCOPES: list[str] = ["*"]


def default_scopes_for_role(role: MemberRole | str) -> list[str]:
    r = role.value if isinstance(role, MemberRole) else role
    if r in (MemberRole.owner.value, MemberRole.admin.value, "owner", "admin"):
        return list(FULL_SCOPES)
    if r in (MemberRole.readonly.value, "readonly"):
        return list(READONLY_SCOPES)
    return list(DEFAULT_AGENT_SCOPES)


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    """Empty/None → full access (legacy). Otherwise dedupe + sort."""
    if not scopes:
        return list(FULL_SCOPES)
    out = sorted({s.strip() for s in scopes if s and s.strip()})
    return out or list(FULL_SCOPES)


def has_scope(granted: list[str] | None, needed: str) -> bool:
    """Return True if ``granted`` satisfies ``needed``."""
    g = normalize_scopes(granted)
    if "*" in g or needed in g:
        return True
    if ":" not in needed:
        return False
    resource, action = needed.split(":", 1)
    if action == "read" and "*:read" in g:
        return True
    if action == "write" and "*:write" in g:
        return True
    if action == "delete" and "*:delete" in g:
        return True
    # write implies read for the same resource
    return action == "read" and f"{resource}:write" in g


def missing_scopes(granted: list[str] | None, *needed: str) -> list[str]:
    return [s for s in needed if not has_scope(granted, s)]


def validate_scope_names(scopes: list[str]) -> list[str]:
    """Return unknown scope names (empty list if all valid)."""
    known = set(all_known_scopes())
    bad: list[str] = []
    for s in scopes:
        if s in known:
            continue
        # allow future resource:action if shape is right
        if ":" in s and s.count(":") == 1:
            res, act = s.split(":")
            if res.isidentifier() and act.isidentifier():
                continue
        bad.append(s)
    return bad
