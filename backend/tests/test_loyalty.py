import threading
from datetime import timedelta

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Customer, LoyaltyProgram, PointLedgerEntry, Redemption, Reward, frozen_clock, utcnow
from app.services import ledger, redemptions

from .conftest import enroll, invite_and_join, purchase


def balance(api, customer_id):
    return api.get(f"/customers/{customer_id}").get_json()["data"]["points_balance"]


def test_purchase_earns_correct_points(owner):
    owner.patch("/programs/current", {"points_per_dollar": 10})
    c = enroll(owner)
    resp = purchase(owner, c["id"], "12.99", owner.location_id)
    assert resp.status_code == 201
    assert resp.get_json()["data"]["purchase"]["points_awarded"] == 129  # floor(12.99 * 10)
    assert balance(owner, c["id"]) == 129


def test_eligible_amount_and_minimum_spend(owner):
    owner.patch("/programs/current", {"points_per_dollar": 2, "min_spend": "5.00"})
    c = enroll(owner)
    below = purchase(owner, c["id"], "4.99", owner.location_id)
    assert below.status_code == 201
    assert below.get_json()["data"]["purchase"]["points_awarded"] == 0
    partial = purchase(owner, c["id"], "30.00", owner.location_id, eligible_amount="20.00")
    assert partial.get_json()["data"]["purchase"]["points_awarded"] == 40
    assert balance(owner, c["id"]) == 40


def test_invalid_purchases_rejected_or_earn_nothing(owner):
    c = enroll(owner)
    for amount in ("-5", "0", "abc", "1.234", None):
        assert purchase(owner, c["id"], amount, owner.location_id).status_code == 422
    too_much = purchase(owner, c["id"], "10.00", owner.location_id, eligible_amount="11.00")
    assert too_much.status_code == 422
    owner.patch("/programs/current", {"earning_enabled": False})
    off = purchase(owner, c["id"], "100.00", owner.location_id)
    assert off.get_json()["data"]["purchase"]["points_awarded"] == 0
    # Missing idempotency key
    resp = owner.post("/purchases", {"customer_id": c["id"], "amount": "5", "location_id": owner.location_id})
    assert resp.status_code == 422
    assert balance(owner, c["id"]) == 0


def test_duplicate_requests_do_not_award_twice(owner):
    c = enroll(owner)
    first = purchase(owner, c["id"], "25.00", owner.location_id, key="same-key-123")
    second = purchase(owner, c["id"], "25.00", owner.location_id, key="same-key-123")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["data"]["duplicate"] is True
    receipt1 = purchase(owner, c["id"], "10.00", owner.location_id, external_ref="R-1")
    receipt2 = purchase(owner, c["id"], "10.00", owner.location_id, external_ref="R-1")
    assert receipt1.status_code == 201
    assert receipt2.status_code == 409
    assert receipt2.get_json()["error"]["code"] == "duplicate_transaction"
    assert balance(owner, c["id"]) == 35
    assert PointLedgerEntry.query.filter_by(customer_id=c["id"]).count() == 2


def _reward(api, cost=100, **extra):
    resp = api.post("/rewards", {"name": "Reward", "reward_type": "free_item", "points_cost": cost, **extra})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]


def _redeem(api, customer_id, reward_id, location_id, key):
    return api.post(
        "/redemptions", {"customer_id": customer_id, "reward_id": reward_id, "location_id": location_id}, idem=key
    )


def test_redemption_success_and_insufficient_points(owner):
    c = enroll(owner)
    reward = _reward(owner, cost=100)
    insufficient = _redeem(owner, c["id"], reward["id"], owner.location_id, "redeem-0001")
    assert insufficient.status_code == 409
    assert insufficient.get_json()["error"]["code"] == "insufficient_points"

    purchase(owner, c["id"], "150.00", owner.location_id)
    ok = _redeem(owner, c["id"], reward["id"], owner.location_id, "redeem-0002")
    assert ok.status_code == 201
    redemption = ok.get_json()["data"]
    assert redemption["status"] == "issued"
    assert len(redemption["code"]) == 8
    assert balance(owner, c["id"]) == 50
    # Duplicate redemption request returns the same code without double debit
    dup = _redeem(owner, c["id"], reward["id"], owner.location_id, "redeem-0002")
    assert dup.status_code == 200
    assert dup.get_json()["data"]["code"] == redemption["code"]
    assert balance(owner, c["id"]) == 50


def test_redemption_status_transitions(owner, new_api):
    staff = invite_and_join(owner, new_api, "staff")
    c = enroll(owner)
    purchase(owner, c["id"], "300.00", owner.location_id)
    reward = _reward(owner, cost=100)
    r1 = _redeem(staff, c["id"], reward["id"], owner.location_id, "redeem-t-01").get_json()["data"]
    lookup = staff.get(f"/redemptions/lookup?code={r1['code'].lower()}")
    assert lookup.status_code == 200
    done = staff.post(f"/redemptions/{r1['id']}/complete", {"location_id": owner.location_id})
    assert done.get_json()["data"]["status"] == "redeemed"
    again = staff.post(f"/redemptions/{r1['id']}/complete", {"location_id": owner.location_id})
    assert again.status_code == 409
    assert owner.post(f"/redemptions/{r1['id']}/cancel", {"reason": "too late"}).status_code == 409

    # Staff cannot cancel; manager/owner can, and the points are refunded
    r2 = _redeem(staff, c["id"], reward["id"], owner.location_id, "redeem-t-02").get_json()["data"]
    assert staff.post(f"/redemptions/{r2['id']}/cancel", {"reason": "changed mind"}).status_code == 403
    before = balance(owner, c["id"])
    cancelled = owner.post(f"/redemptions/{r2['id']}/cancel", {"reason": "changed mind"})
    assert cancelled.get_json()["data"]["status"] == "cancelled"
    assert balance(owner, c["id"]) == before + 100
    assert owner.post(f"/redemptions/{r2['id']}/complete", {"location_id": owner.location_id}).status_code == 409


def test_expired_code_refunds_and_cannot_complete(owner):
    c = enroll(owner)
    purchase(owner, c["id"], "100.00", owner.location_id)
    reward = _reward(owner, cost=100)
    r = _redeem(owner, c["id"], reward["id"], owner.location_id, "redeem-e-01").get_json()["data"]
    row = db.session.get(Redemption, r["id"])
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    resp = owner.post(f"/redemptions/{r['id']}/complete", {"location_id": owner.location_id})
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "code_expired"
    assert balance(owner, c["id"]) == 100


def test_stock_limit_enforced(owner):
    reward = _reward(owner, cost=10, stock_limit=1)
    a, b = enroll(owner), enroll(owner)
    purchase(owner, a["id"], "50", owner.location_id)
    purchase(owner, b["id"], "50", owner.location_id)
    assert _redeem(owner, a["id"], reward["id"], owner.location_id, "stock-0001").status_code == 201
    out = _redeem(owner, b["id"], reward["id"], owner.location_id, "stock-0002")
    assert out.status_code == 409
    assert out.get_json()["error"]["code"] == "out_of_stock"
    assert balance(owner, b["id"]) == 50


def test_reversal_creates_new_entry(owner):
    c = enroll(owner)
    purchase(owner, c["id"], "40.00", owner.location_id)
    entry = owner.get(f"/customers/{c['id']}/ledger").get_json()["data"][0]
    assert owner.post(f"/ledger/{entry['id']}/reverse", {"reason": ""}).status_code == 422
    rev = owner.post(f"/ledger/{entry['id']}/reverse", {"reason": "Wrong customer"})
    assert rev.status_code == 201
    assert rev.get_json()["data"]["points"] == -40
    assert balance(owner, c["id"]) == 0
    assert owner.post(f"/ledger/{entry['id']}/reverse", {"reason": "Again"}).status_code == 409
    entries = owner.get(f"/customers/{c['id']}/ledger").get_json()["data"]
    assert len(entries) == 2  # original preserved + reversal
    assert next(e for e in entries if e["id"] == entry["id"])["reversed"] is True


def test_reversal_cannot_overdraw(owner):
    c = enroll(owner)
    purchase(owner, c["id"], "100.00", owner.location_id)
    reward = _reward(owner, cost=80)
    _redeem(owner, c["id"], reward["id"], owner.location_id, "rev-od-01")
    award = [e for e in owner.get(f"/customers/{c['id']}/ledger").get_json()["data"] if e["entry_type"] == "award"][0]
    resp = owner.post(f"/ledger/{award['id']}/reverse", {"reason": "Refunded purchase"})
    assert resp.status_code == 409
    assert balance(owner, c["id"]) == 20


def test_manual_adjustments_need_reason_and_permission(owner, new_api):
    c = enroll(owner)
    assert owner.post(f"/customers/{c['id']}/adjustments", {"points": 50}).status_code == 422
    assert owner.post(f"/customers/{c['id']}/adjustments", {"points": 0, "reason": "zero"}).status_code == 422
    ok = owner.post(f"/customers/{c['id']}/adjustments", {"points": 50, "reason": "Service recovery"})
    assert ok.status_code == 201
    assert ok.get_json()["data"]["actor"] == "Owner One"
    assert owner.post(f"/customers/{c['id']}/adjustments", {"points": -60, "reason": "Too many"}).status_code == 409
    manager = invite_and_join(owner, new_api, "manager")
    assert manager.post(f"/customers/{c['id']}/adjustments", {"points": -10, "reason": "Correction"}).status_code == 201
    staff = invite_and_join(owner, new_api, "staff")
    assert staff.post(f"/customers/{c['id']}/adjustments", {"points": 10, "reason": "Friend"}).status_code == 403
    assert balance(owner, c["id"]) == 40


def test_ledger_rows_are_append_only(owner):
    c = enroll(owner)
    purchase(owner, c["id"], "10", owner.location_id)
    entry = PointLedgerEntry.query.filter_by(customer_id=c["id"]).first()
    entry.points = 9999
    with pytest.raises(RuntimeError):
        db.session.flush()
    db.session.rollback()
    with pytest.raises(RuntimeError):
        db.session.delete(PointLedgerEntry.query.first())
        db.session.flush()
    db.session.rollback()


def test_balances_reconcile_with_ledger(owner):
    c = enroll(owner)
    purchase(owner, c["id"], "70", owner.location_id)
    owner.post(f"/customers/{c['id']}/adjustments", {"points": -5, "reason": "Fix"})
    result = owner.get(f"/customers/{c['id']}/reconcile").get_json()["data"]
    assert result == {"consistent": True, "mismatches": [], "balance": 65}


def test_points_expiry_is_consistent(owner):
    owner.patch("/programs/current", {"points_expiry_days": 30})
    c = enroll(owner)
    purchase(owner, c["id"], "50", owner.location_id)
    business_id = owner.business["id"]
    assert ledger.process_expirations(business_id) == 0  # still active
    later = utcnow() + timedelta(days=31)
    with frozen_clock(later):
        assert ledger.process_expirations(business_id) == 1
        assert ledger.process_expirations(business_id) == 0  # idempotent
    db.session.commit()
    assert balance(owner, c["id"]) == 0
    types = [e["entry_type"] for e in owner.get(f"/customers/{c['id']}/ledger").get_json()["data"]]
    assert types == ["expiration", "award"]
    assert owner.patch("/programs/current", {"points_expiry_days": 5}).status_code == 422


def test_concurrent_redemptions_cannot_overdraw(tmp_path):
    """Several threads redeem against a balance that only covers two redemptions."""
    db_path = tmp_path / "concurrency.db"
    app = create_app(TestConfig, {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})
    with app.app_context():
        db.create_all()
        from app.models import Business

        business = Business(name="Race", slug="race")
        db.session.add(business)
        db.session.flush()
        db.session.add(LoyaltyProgram(business_id=business.id, name="P"))
        reward = Reward(business_id=business.id, name="R", reward_type="custom", points_cost=100)
        customer = Customer(business_id=business.id, display_name="C", referral_code="RACE0001")
        db.session.add_all([reward, customer])
        db.session.flush()
        ledger.post_entry(customer, 250, "adjustment", reason="seed")
        db.session.commit()
        ids = (business.id, customer.id, reward.id)

    results = []
    barrier = threading.Barrier(6)

    def worker(n):
        with app.app_context():
            barrier.wait()
            try:
                c = db.session.get(Customer, ids[1])
                r = db.session.get(Reward, ids[2])
                redemptions.issue(ids[0], c, r, f"race-{n}")
                db.session.commit()
                results.append("ok")
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                results.append(type(exc).__name__)
            finally:
                db.session.remove()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with app.app_context():
        customer = db.session.get(Customer, ids[1])
        assert results.count("ok") == 2, results
        assert customer.points_balance == 50
        assert ledger.reconcile(ids[0]) == []
        db.drop_all()
