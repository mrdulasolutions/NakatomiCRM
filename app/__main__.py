"""Allow ``python -m app`` to run the operator CLI."""

from app.cli import main

raise SystemExit(main())
