"""In-process background tasks used for single-service hosting."""

from datetime import timedelta

from app import background
from app.extensions import db
from app.models import Customer, NotificationOutbox, Redemption, utcnow
from app.services import ledger

from .conftest import enroll, purchase


def test_tick_sends_email_and_runs_maintenance(app, owner):
    owner.patch("/programs/current", {"points_expiry_days": 30, "birthday_bonus_points": 10})
    c = enroll(owner, "Old", email="old@example.com")
    purchase(owner, c["id"], "50", owner.location_id)
    row = db.session.get(Customer, c["id"])
    row.last_activity_at = utcnow() - timedelta(days=60)
    db.session.commit()
    pending = NotificationOutbox.query.filter_by(status="pending").count()
    assert pending >= 1  # signup verification email

    state = {}
    background.tick(app, now=1_000_000.0, state=state)
    assert NotificationOutbox.query.filter_by(status="pending").count() == 0
    assert db.session.get(Customer, c["id"]).points_balance == 0  # expired by maintenance
    assert ledger.reconcile(owner.business["id"]) == []

    # Not due again yet: nothing re-runs, and re-running later is harmless (idempotent).
    background.tick(app, now=1_000_001.0, state=state)
    background.tick(app, now=1_000_000.0 + 7200, state=state)
    assert db.session.get(Customer, c["id"]).points_balance == 0


def test_maintenance_expires_stale_codes(app, owner):
    c = enroll(owner)
    purchase(owner, c["id"], "100", owner.location_id)
    reward = owner.post("/rewards", {"name": "R", "reward_type": "free_item", "points_cost": 50}).get_json()["data"]
    code = owner.post(
        "/redemptions",
        {"customer_id": c["id"], "reward_id": reward["id"], "location_id": owner.location_id},
        idem="bg-redeem-1",
    ).get_json()["data"]
    r = db.session.get(Redemption, code["id"])
    r.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    totals = background.run_maintenance()
    db.session.commit()
    assert totals["expired_codes"] == 1
    assert db.session.get(Customer, c["id"]).points_balance == 100


def test_background_thread_not_started_in_tests_or_when_disabled(app):
    app.config["RUN_BACKGROUND_IN_WEB"] = True  # TESTING still blocks it
    assert background.ensure_started(app) is False
    app.config.update(RUN_BACKGROUND_IN_WEB=False, TESTING=False)
    assert background.ensure_started(app) is False
    app.config["TESTING"] = True
