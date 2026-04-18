"""One-shot seed: create a demo workspace, owner, api key, and a default pipeline.

Usage:
    python -m scripts.seed --email owner@example.com --password hunter22secret \
        --workspace-name "Demo Inc" --workspace-slug demo
"""

from __future__ import annotations

import argparse

from app.db import SessionLocal
from app.models import (
    ApiKey,
    Membership,
    MemberRole,
    Pipeline,
    Stage,
    User,
    Workspace,
)
from app.security import generate_api_key, hash_password


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--workspace-name", required=True)
    ap.add_argument("--workspace-slug", required=True)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.lower()).one_or_none()
        if not user:
            user = User(
                email=args.email.lower(),
                password_hash=hash_password(args.password),
                display_name=args.email.split("@")[0],
            )
            db.add(user)
            db.flush()

        ws = db.query(Workspace).filter(Workspace.slug == args.workspace_slug).one_or_none()
        if not ws:
            ws = Workspace(name=args.workspace_name, slug=args.workspace_slug)
            db.add(ws)
            db.flush()

        if not db.query(Membership).filter_by(workspace_id=ws.id, user_id=user.id).first():
            db.add(Membership(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))

        pipe = db.query(Pipeline).filter_by(workspace_id=ws.id, slug="sales").one_or_none()
        if not pipe:
            pipe = Pipeline(workspace_id=ws.id, name="Sales", slug="sales", is_default=True)
            db.add(pipe)
            db.flush()
            stages = [
                ("Lead", "lead", 0, 10, False, False),
                ("Qualified", "qualified", 1, 25, False, False),
                ("Proposal", "proposal", 2, 50, False, False),
                ("Negotiation", "negotiation", 3, 75, False, False),
                ("Won", "won", 4, 100, True, False),
                ("Lost", "lost", 5, 0, False, True),
            ]
            for name, slug, pos, prob, won, lost in stages:
                db.add(Stage(pipeline_id=pipe.id, name=name, slug=slug,
                             position=pos, probability=prob, is_won=won, is_lost=lost))

        full, prefix, digest = generate_api_key()
        key = ApiKey(
            workspace_id=ws.id, user_id=user.id,
            name="seed-key", prefix=prefix, key_hash=digest, role=MemberRole.owner,
        )
        db.add(key)
        db.commit()

        print("\nSeed complete.")
        print(f"  workspace: {ws.slug} ({ws.id})")
        print(f"  owner:     {user.email} ({user.id})")
        print(f"  api key:   {full}")
        print("\nStore the api key — it cannot be retrieved later.\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
