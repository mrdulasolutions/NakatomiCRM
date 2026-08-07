"""Protocol contract versions and stability SLA for v1.0+.

Agents should read these from ``GET /schema``, ``GET /discovery``, or
``GET /health``. Breaking changes to a protocol surface require a **major**
Nakatomi version bump and a documented sunset window (see
``docs/PROTOCOL_SLA.md``).
"""

from __future__ import annotations

from typing import Any

# Surface contract versions (independent of app SemVer when additive-only).
PROTOCOL_VERSIONS: dict[str, str] = {
    "rest": "1.0",
    "mcp": "1.0",
    "a2a": "1.0",
    "acp": "1.0",
}

# Minimum notice (days) before a breaking protocol change takes effect
# after announcement in CHANGELOG + /schema.sunset.
SUNSET_NOTICE_DAYS = 90

# Currently scheduled sunsets. Empty at 1.0 ship.
# Shape: [{"surface": "mcp", "from_version": "1.0", "to_version": "2.0",
#          "remove_after": "YYYY-MM-DD", "notes": "..."}]
SCHEDULED_SUNSETS: list[dict[str, Any]] = []

STABILITY_TIER = "stable"  # pre-1.0 was "beta"


def protocol_manifest() -> dict[str, Any]:
    """Machine-readable SLA block embedded in discovery surfaces."""
    return {
        "stability": STABILITY_TIER,
        "versions": dict(PROTOCOL_VERSIONS),
        "sunset_notice_days": SUNSET_NOTICE_DAYS,
        "scheduled_sunsets": list(SCHEDULED_SUNSETS),
        "policy": (
            "Breaking MCP/A2A/ACP/REST contract changes require a major SemVer "
            f"bump and ≥{SUNSET_NOTICE_DAYS} days notice via CHANGELOG and "
            "this `scheduled_sunsets` list. Additive fields and new endpoints "
            "are minor/patch and need no sunset."
        ),
        "docs": "/docs/PROTOCOL_SLA.md",
    }
