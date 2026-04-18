"""Find likely duplicate contacts using a short cascade of SQL signals.

Strategies, highest confidence first:

1. **exact_email** — two live contacts share the same email (case-insensitive).
   Score: 1.0. Near-certain duplicate.
2. **name_similar_same_company** — full-name trigram similarity > 0.80 AND
   both contacts point at the same ``company_id``. Score: 0.8. Catches the
   common "Ada Lovelace" ↔ "Ada L." case when the company is known.
3. **last_name_same_first_similar** — identical last name (case-insensitive)
   AND first-name trigram similarity > 0.70. Score: 0.7. Good at catching
   typos in the first name.

Pairs are deduplicated across strategies — each (a, b) surfaces once with
the highest score found. Backed by the trigram GIN indexes added in
migration 0006. Without pg_trgm, every query falls back to a sequential
similarity() evaluation; it still works, just slower.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class DuplicatePair:
    a_id: str
    b_id: str
    score: float
    reason: str


_SQL = """
WITH
exact_email AS (
    SELECT a.id AS a_id, b.id AS b_id, 1.0::float AS score, 'exact_email' AS reason
    FROM contacts a
    JOIN contacts b
      ON a.workspace_id = b.workspace_id
     AND lower(a.email) = lower(b.email)
     AND a.id < b.id
    WHERE a.workspace_id = :ws
      AND a.email IS NOT NULL
      AND a.deleted_at IS NULL
      AND b.deleted_at IS NULL
),
name_same_company AS (
    SELECT a.id AS a_id, b.id AS b_id, 0.8::float AS score, 'name_similar_same_company' AS reason
    FROM contacts a
    JOIN contacts b
      ON a.workspace_id = b.workspace_id
     AND a.company_id = b.company_id
     AND a.id < b.id
    WHERE a.workspace_id = :ws
      AND a.company_id IS NOT NULL
      AND a.deleted_at IS NULL
      AND b.deleted_at IS NULL
      AND similarity(
            coalesce(a.first_name,'') || ' ' || coalesce(a.last_name,''),
            coalesce(b.first_name,'') || ' ' || coalesce(b.last_name,'')
          ) > :name_threshold
),
last_name_same AS (
    SELECT a.id AS a_id, b.id AS b_id, 0.7::float AS score, 'last_name_same_first_similar' AS reason
    FROM contacts a
    JOIN contacts b
      ON a.workspace_id = b.workspace_id
     AND lower(a.last_name) = lower(b.last_name)
     AND a.id < b.id
    WHERE a.workspace_id = :ws
      AND a.last_name IS NOT NULL
      AND a.deleted_at IS NULL
      AND b.deleted_at IS NULL
      AND similarity(coalesce(a.first_name,''), coalesce(b.first_name,'')) > :first_threshold
),
combined AS (
    SELECT * FROM exact_email
    UNION ALL SELECT * FROM name_same_company
    UNION ALL SELECT * FROM last_name_same
),
best AS (
    SELECT DISTINCT ON (a_id, b_id) a_id, b_id, score, reason
    FROM combined
    ORDER BY a_id, b_id, score DESC
)
SELECT a_id, b_id, score, reason
FROM best
WHERE score >= :min_score
ORDER BY score DESC, a_id, b_id
LIMIT :limit
"""


def find_duplicates(
    db: Session,
    workspace_id: str,
    *,
    min_score: float = 0.7,
    limit: int = 100,
    name_threshold: float = 0.80,
    first_threshold: float = 0.70,
) -> list[DuplicatePair]:
    rows = db.execute(
        text(_SQL),
        {
            "ws": workspace_id,
            "min_score": min_score,
            "limit": min(limit, 500),
            "name_threshold": name_threshold,
            "first_threshold": first_threshold,
        },
    ).all()
    return [DuplicatePair(a_id=r[0], b_id=r[1], score=float(r[2]), reason=r[3]) for r in rows]


def serialize(pairs: list[DuplicatePair]) -> list[dict[str, Any]]:
    return [{"a_id": p.a_id, "b_id": p.b_id, "score": p.score, "reason": p.reason} for p in pairs]
