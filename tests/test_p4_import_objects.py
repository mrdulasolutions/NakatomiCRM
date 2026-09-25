"""P4: CRM importers + custom objects."""

from __future__ import annotations


def test_hubspot_import_dry_and_live(client, workspace):
    h = workspace["headers"]
    payload = {
        "companies": [{"id": "10", "properties": {"name": "Hub Co", "domain": "hubco.example"}}],
        "contacts": [
            {
                "id": "20",
                "properties": {
                    "email": "hub@hubco.example",
                    "firstname": "Hub",
                    "lastname": "Person",
                    "associatedcompanyid": "10",
                },
            }
        ],
        "deals": [
            {
                "id": "30",
                "properties": {"dealname": "Hub Deal", "amount": "1500", "dealstage": "appointmentscheduled"},
            }
        ],
    }
    r = client.post(
        "/import/crm",
        headers=h,
        json={"source": "hubspot", "payload": payload, "dry_run": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"].get("companies", 0) >= 1
    assert r.json()["dry_run"] is True

    r = client.post(
        "/import/crm",
        headers=h,
        json={"source": "hubspot", "payload": payload, "dry_run": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"].get("contacts", 0) >= 1

    # re-import updates
    r = client.post(
        "/import/crm",
        headers=h,
        json={"source": "hubspot", "payload": payload, "dry_run": False},
    )
    assert r.json()["updated"].get("contacts", 0) >= 1

    r = client.get("/contacts", headers=h, params={"email": "hub@hubco.example"})
    assert r.json()["count"] >= 1


def test_salesforce_and_generic_import(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/import/crm",
        headers=h,
        json={
            "source": "salesforce",
            "payload": {
                "Account": [{"Id": "001", "Name": "SF Co", "Website": "sf.example"}],
                "Contact": [
                    {
                        "Id": "003",
                        "Email": "sf@sf.example",
                        "FirstName": "Sf",
                        "LastName": "User",
                        "AccountId": "001",
                    }
                ],
                "Opportunity": [{"Id": "006", "Name": "Big Opp", "Amount": 9000, "StageName": "Prospecting"}],
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"].get("deals", 0) >= 1

    r = client.post(
        "/import/crm",
        headers=h,
        json={
            "source": "generic",
            "payload": {"contacts": [{"email": "gen@example.com", "first_name": "Gen", "external_id": "g1"}]},
        },
    )
    assert r.status_code == 200
    assert r.json()["created"].get("contacts", 0) >= 1


def test_custom_objects_crud(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/custom-objects/types",
        headers=h,
        json={
            "name": "Partner",
            "slug": "partner",
            "fields": [
                {"name": "region", "label": "Region", "type": "string", "required": True},
                {"name": "tier", "label": "Tier", "type": "select", "options": ["A", "B"]},
            ],
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/custom-objects/types/partner/records",
        headers=h,
        json={
            "name": "Acme Partner",
            "external_id": "p-1",
            "values": {"region": "US", "tier": "A"},
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    # upsert
    r = client.post(
        "/custom-objects/types/partner/records",
        headers=h,
        json={
            "name": "Acme Partner LLC",
            "external_id": "p-1",
            "values": {"region": "US", "tier": "B"},
        },
    )
    assert r.status_code == 201
    assert r.json()["id"] == rid
    assert r.json()["values"]["tier"] == "B"

    r = client.get("/custom-objects/types/partner/records", headers=h, params={"q": "Acme"})
    assert r.status_code == 200
    assert len(r.json()) >= 1

    r = client.delete(f"/custom-objects/types/partner/records/{rid}", headers=h)
    assert r.status_code == 200


def test_unknown_import_source(client, workspace):
    r = client.post(
        "/import/crm",
        headers=workspace["headers"],
        json={"source": "not-a-crm", "payload": {}},
    )
    assert r.status_code == 200
    assert r.json()["errors"]
