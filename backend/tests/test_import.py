"""CSV customer import."""

from app.extensions import db
from app.models import ConsentRecord, Customer, PointLedgerEntry
from app.services import ledger

from .conftest import enroll, invite_and_join

GOOD = """Name,Email,Phone,Birthday,Points,Marketing
Ava Lee,ava.lee@example.com,(503) 555-0101,03-14,250,yes
Ben Ortiz,BEN@example.com,,1990-07-04,0,no
Cara Diaz,,503-555-0199,,,
"""


def _import(api, csv_text, dry_run=True, **opts):
    return api.post("/customers/import", {"csv": csv_text, "dry_run": dry_run, **opts})


def test_preview_does_not_write(owner):
    resp = _import(owner, GOOD, import_points=True)
    data = resp.get_json()["data"]
    assert resp.status_code == 200 and data["imported"] is False
    assert data["summary"] == {
        "rows": 3,
        "create": 3,
        "skip": 0,
        "error": 0,
        "opening_points": 250,
        "marketing_opt_ins": 0,
    }
    assert data["sample"][0]["display_name"] == "Ava Lee" and data["sample"][0]["phone"] == "+15035550101"
    assert Customer.query.count() == 0


def test_import_creates_customers_balances_and_consent(owner):
    resp = _import(owner, GOOD, dry_run=False, import_points=True, import_consent=True)
    data = resp.get_json()["data"]
    assert data["imported"] is True and data["summary"]["create"] == 3 and data["summary"]["marketing_opt_ins"] == 1
    ava = Customer.query.filter_by(email_normalized="ava.lee@example.com").one()
    assert (ava.points_balance, ava.birth_month, ava.birth_day, ava.marketing_opt_in) == (250, 3, 14, True)
    assert ConsentRecord.query.filter_by(customer_id=ava.id, source="import").count() == 1
    entry = PointLedgerEntry.query.filter_by(customer_id=ava.id).one()
    assert entry.entry_type == "adjustment" and "imported" in entry.reason.lower()
    assert Customer.query.filter_by(email_normalized="ben@example.com").one().birth_month == 7
    assert ledger.reconcile(owner.business["id"]) == []
    actions = [a["action"] for a in owner.get("/audit-logs").get_json()["data"]]
    assert "customers.imported" in actions


def test_consent_and_points_ignored_unless_confirmed(owner):
    _import(owner, GOOD, dry_run=False)
    ava = Customer.query.filter_by(email_normalized="ava.lee@example.com").one()
    assert ava.points_balance == 0 and ava.marketing_opt_in is False


def test_duplicates_skipped_and_errors_block_import(owner):
    enroll(owner, "Existing", email="exists@example.com")
    csv_text = """full name;e-mail;mobile;dob
Existing Person;EXISTS@example.com;;
New One;new@example.com;;
Dup One;new@example.com;;
;nobody@example.com;;
No Contact;;;
Bad Email;not-an-email;;
Bad Phone;;12345;
Bad Bday;b@example.com;;13-40
"""
    preview = _import(owner, csv_text).get_json()["data"]
    assert preview["summary"]["create"] == 1  # only "New One"
    reasons = {s["line"]: s["reason"] for s in preview["skipped"]}
    assert "Already a customer" in reasons[2] and "Duplicate email" in reasons[4]
    error_lines = {e["line"] for e in preview["errors"]}
    assert error_lines == {5, 6, 7, 8, 9}
    blocked = _import(owner, csv_text, dry_run=False)
    assert blocked.status_code == 422 and blocked.get_json()["error"]["code"] == "import_has_errors"
    assert Customer.query.count() == 1  # nothing imported


def test_header_validation_and_size(owner):
    assert _import(owner, "email\nx@example.com\n").status_code == 422  # no name column
    assert _import(owner, "name\nAva\n").status_code == 422  # no contact column
    assert _import(owner, "").status_code == 422
    resp = _import(owner, "﻿First Name,Last Name,Email,Favourite Colour\nAva,Lee,ava@example.com,blue\n")
    data = resp.get_json()["data"]
    assert data["sample"][0]["display_name"] == "Ava Lee"
    assert data["unknown_columns"] == ["Favourite Colour"]


def test_plan_limit_enforced(owner, monkeypatch):
    from app import billing

    owner.post("/billing/dev/switch", {"plan": "starter"})
    monkeypatch.setitem(billing.PLANS["starter"]["limits"], "customers", 2)
    preview = _import(owner, GOOD).get_json()["data"]
    assert preview["limit"]["over_limit"] is True
    resp = _import(owner, GOOD, dry_run=False)
    assert resp.status_code == 402 and resp.get_json()["error"]["code"] == "plan_limit_reached"
    assert Customer.query.count() == 0


def test_permissions_and_tenant_isolation(owner, new_api):
    staff = invite_and_join(owner, new_api, "staff")
    assert _import(staff, GOOD).status_code == 403
    manager = invite_and_join(owner, new_api, "manager")
    assert _import(manager, GOOD, dry_run=False).get_json()["data"]["imported"] is True
    assert Customer.query.filter(Customer.business_id != owner.business["id"]).count() == 0
    db.session.rollback()
