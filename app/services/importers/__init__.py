"""One-shot CRM importers (agent-driven mapping, no UI)."""

from app.services.importers.base import ImportResult, run_crm_import

__all__ = ["ImportResult", "run_crm_import"]
