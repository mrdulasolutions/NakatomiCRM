"""Validate deal references against the workspace and selected pipeline."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Company, Contact, Membership, Pipeline, Stage


def validate_deal_references(
    db: Session, workspace_id: str, pipeline_id: str, stage_id: str, fields: dict
) -> None:
    try:
        pipeline = db.get(Pipeline, str(UUID(pipeline_id)))
        stage = db.get(Stage, str(UUID(stage_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid pipeline or stage") from exc
    if not pipeline or pipeline.workspace_id != workspace_id or not stage or stage.pipeline_id != pipeline.id:
        raise ValueError("Stage must belong to a pipeline in this workspace")
    for field, model in (("primary_contact_id", Contact), ("company_id", Company)):
        if fields.get(field):
            try:
                row = db.get(model, str(UUID(fields[field])))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"Invalid {field}") from exc
            if not row or row.workspace_id != workspace_id or row.deleted_at:
                raise ValueError(f"{field} must belong to this workspace")
    if fields.get("owner_user_id"):
        from sqlalchemy import select

        try:
            owner = str(UUID(fields["owner_user_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid deal owner") from exc
        if not db.scalar(
            select(Membership.id).where(Membership.workspace_id == workspace_id, Membership.user_id == owner)
        ):
            raise ValueError("Deal owner must belong to this workspace")
