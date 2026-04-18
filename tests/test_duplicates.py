"""GET /contacts/duplicates — fuzzy duplicate detection."""

from __future__ import annotations


def _mk(client, h, **kw) -> dict:
    return client.post("/contacts", headers=h, json=kw).json()


def test_empty_workspace_returns_no_pairs(client, workspace):
    r = client.get("/contacts/duplicates", headers=workspace["headers"])
    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0}


def test_exact_email_match_scores_1_0(client, workspace):
    h = workspace["headers"]
    _mk(client, h, first_name="Ada", email="ada@example.com")
    _mk(client, h, first_name="A.", email="ADA@example.COM")  # case-insensitive
    # Add an unrelated contact so the query has more to chew on.
    _mk(client, h, first_name="Grace", email="grace@example.com")

    r = client.get("/contacts/duplicates", headers=h)
    pairs = r.json()["items"]
    assert len(pairs) == 1
    assert pairs[0]["score"] == 1.0
    assert pairs[0]["reason"] == "exact_email"


def test_similar_name_same_company_scores_0_8(client, workspace):
    h = workspace["headers"]
    co = client.post("/companies", headers=h, json={"name": "Acme"}).json()
    _mk(client, h, first_name="Ada", last_name="Lovelace", company_id=co["id"])
    _mk(client, h, first_name="Ada", last_name="Lovelacce", company_id=co["id"])  # typo

    r = client.get("/contacts/duplicates", headers=h)
    pairs = r.json()["items"]
    assert len(pairs) == 1
    assert pairs[0]["reason"] == "name_similar_same_company"
    assert pairs[0]["score"] == 0.8


def test_same_last_name_first_variant(client, workspace):
    """Prefix matching catches nickname/long-form pairs like Tom/Thomas."""
    h = workspace["headers"]
    _mk(client, h, first_name="Tom", last_name="Hanks")
    _mk(client, h, first_name="Thomas", last_name="Hanks")

    r = client.get("/contacts/duplicates", headers=h)
    pairs = r.json()["items"]
    assert len(pairs) == 1
    assert pairs[0]["reason"] == "last_name_same_first_variant"


def test_same_last_name_different_first_name_not_matched(client, workspace):
    """Different first names (no prefix overlap) should NOT surface as a dup."""
    h = workspace["headers"]
    _mk(client, h, first_name="Ada", last_name="Hopper")
    _mk(client, h, first_name="Grace", last_name="Hopper")

    r = client.get("/contacts/duplicates", headers=h)
    assert r.json() == {"items": [], "count": 0}


def test_strongest_reason_wins_when_multiple_strategies_match(client, workspace):
    """Same-email + same-last-name should surface once with score=1.0."""
    h = workspace["headers"]
    _mk(client, h, first_name="Ada", last_name="Lovelace", email="ada@example.com")
    _mk(client, h, first_name="Ada", last_name="Lovelace", email="ada@example.com")

    r = client.get("/contacts/duplicates", headers=h)
    pairs = r.json()["items"]
    assert len(pairs) == 1
    assert pairs[0]["score"] == 1.0
    assert pairs[0]["reason"] == "exact_email"


def test_no_false_positives_for_unrelated_contacts(client, workspace):
    h = workspace["headers"]
    _mk(client, h, first_name="Ada", last_name="Lovelace")
    _mk(client, h, first_name="Bob", last_name="Smith")
    _mk(client, h, first_name="Grace", last_name="Hopper")

    r = client.get("/contacts/duplicates", headers=h)
    assert r.json() == {"items": [], "count": 0}


def test_deleted_contacts_ignored(client, workspace):
    h = workspace["headers"]
    a = _mk(client, h, first_name="Ada", email="ada@example.com")
    _mk(client, h, first_name="Ada", email="ada@example.com")  # duplicate

    # Soft-delete one side; duplicates query should drop the pair.
    client.delete(f"/contacts/{a['id']}", headers=h)

    r = client.get("/contacts/duplicates", headers=h)
    assert r.json() == {"items": [], "count": 0}


def test_duplicates_feeds_into_merge(client, workspace):
    """End-to-end: detect the pair, then merge it. The loop must close."""
    h = workspace["headers"]
    a = _mk(client, h, first_name="Ada", last_name="Lovelace", email="ada@example.com")
    b = _mk(client, h, first_name="Ada", email="ada@example.com", title="Mathematician")

    pairs = client.get("/contacts/duplicates", headers=h).json()["items"]
    assert len(pairs) == 1

    # Merge — pick the first as winner.
    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": a["id"], "loser_id": b["id"]},
    )
    assert r.status_code == 200

    # Run detection again — no more duplicates.
    pairs2 = client.get("/contacts/duplicates", headers=h).json()["items"]
    assert pairs2 == []


def test_min_score_filter(client, workspace):
    h = workspace["headers"]
    _mk(client, h, first_name="Tom", last_name="Hanks")
    _mk(client, h, first_name="Thomas", last_name="Hanks")  # 0.7 pair

    # Default min_score=0.7 catches it.
    r = client.get("/contacts/duplicates", headers=h)
    assert r.json()["count"] == 1

    # Raising the threshold above 0.7 drops it.
    r = client.get("/contacts/duplicates?min_score=0.75", headers=h)
    assert r.json()["count"] == 0
