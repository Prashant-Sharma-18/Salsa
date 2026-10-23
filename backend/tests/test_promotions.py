"""Promotions (multipliers, bonuses) and birthday bonuses."""

from datetime import datetime

from app.extensions import db
from app.models import Business, Customer, PointLedgerEntry, frozen_clock
from app.services import promotions

from .conftest import enroll, invite_and_join, purchase

TUESDAY_NOON_ET = datetime(2026, 10, 20, 16, 0)  # 12:00 in New York, Tuesday
TUESDAY_LATE_ET = datetime(2026, 10, 21, 2, 0)  # 22:00 Tuesday in New York, already Wednesday in UTC
WEDNESDAY_NOON_ET = datetime(2026, 10, 21, 16, 0)


def _promo(api, **overrides):
    payload = {
        "name": "Double Tuesdays",
        "promo_type": "multiplier",
        "multiplier_percent": 200,
        "starts_on": "2026-10-01",
        "days_of_week": [1],
        **overrides,
    }
    resp = api.post("/promotions", payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]


def _award(api, cid, amount, location_id, at):
    with frozen_clock(at):
        resp = purchase(api, cid, amount, location_id)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["purchase"]


def test_multiplier_applies_on_matching_local_weekday(owner):
    _promo(owner)
    c = enroll(owner)
    tue = _award(owner, c["id"], "20.00", owner.location_id, TUESDAY_NOON_ET)
    assert (tue["points_awarded"], tue["promotion_points"]) == (40, 20)
    assert tue["promotions_applied"][0]["name"] == "Double Tuesdays"
    late = _award(owner, c["id"], "10.00", owner.location_id, TUESDAY_LATE_ET)  # business time zone decides
    assert late["points_awarded"] == 20
    wed = _award(owner, c["id"], "10.00", owner.location_id, WEDNESDAY_NOON_ET)
    assert wed["points_awarded"] == 10
    entry = PointLedgerEntry.query.filter_by(customer_id=c["id"]).order_by(PointLedgerEntry.id).first()
    assert "Double Tuesdays" in entry.reason


def test_best_multiplier_wins_and_bonuses_stack(owner):
    _promo(owner, name="Double", multiplier_percent=200, days_of_week=[])
    _promo(owner, name="Triple", multiplier_percent=300, days_of_week=[])
    _promo(owner, name="Bonus A", promo_type="bonus", bonus_points=15, multiplier_percent=None, days_of_week=[])
    _promo(owner, name="Bonus B", promo_type="bonus", bonus_points=5, multiplier_percent=None, days_of_week=[])
    c = enroll(owner)
    p = _award(owner, c["id"], "10.00", owner.location_id, TUESDAY_NOON_ET)
    assert p["points_awarded"] == 10 + 20 + 15 + 5
    assert [a["name"] for a in p["promotions_applied"]] == ["Triple", "Bonus A", "Bonus B"]


def test_date_range_location_and_min_spend(owner):
    second = owner.post("/locations", {"name": "Second"}).get_json()["data"]
    _promo(owner, name="Ended", days_of_week=[], ends_on="2026-10-10")
    _promo(owner, name="Future", days_of_week=[], starts_on="2026-11-01")
    _promo(
        owner,
        name="Second only",
        promo_type="bonus",
        bonus_points=50,
        multiplier_percent=None,
        days_of_week=[],
        location_ids=[second["id"]],
        min_spend="25.00",
    )
    c = enroll(owner)
    assert _award(owner, c["id"], "30.00", owner.location_id, TUESDAY_NOON_ET)["promotion_points"] == 0
    assert _award(owner, c["id"], "20.00", second["id"], TUESDAY_NOON_ET)["promotion_points"] == 0  # below min spend
    assert _award(owner, c["id"], "30.00", second["id"], TUESDAY_NOON_ET)["promotion_points"] == 50


def test_promotions_need_base_points_and_active_status(owner):
    promo = _promo(owner, promo_type="bonus", bonus_points=100, multiplier_percent=None, days_of_week=[])
    owner.patch("/programs/current", {"min_spend": "5.00"})
    c = enroll(owner)
    assert _award(owner, c["id"], "4.00", owner.location_id, TUESDAY_NOON_ET)["points_awarded"] == 0
    owner.patch(f"/promotions/{promo['id']}", {"status": "archived"})
    assert _award(owner, c["id"], "10.00", owner.location_id, TUESDAY_NOON_ET)["points_awarded"] == 10


def test_reversal_removes_promotion_points_too(owner):
    _promo(owner, days_of_week=[])
    c = enroll(owner)
    _award(owner, c["id"], "10.00", owner.location_id, TUESDAY_NOON_ET)
    entry = owner.get(f"/customers/{c['id']}/ledger").get_json()["data"][0]
    owner.post(f"/ledger/{entry['id']}/reverse", {"reason": "Returned item"})
    assert owner.get(f"/customers/{c['id']}").get_json()["data"]["points_balance"] == 0


def test_promotion_validation_and_permissions(owner, new_api):
    bad = owner.post("/promotions", {"name": "X", "promo_type": "multiplier", "starts_on": "2026-10-01"})
    assert bad.status_code == 422 and "multiplier_percent" in bad.get_json()["error"]["fields"]
    bad = owner.post(
        "/promotions",
        {"name": "X", "promo_type": "bonus", "bonus_points": 5, "starts_on": "2026-10-05", "ends_on": "2026-10-01"},
    )
    assert "ends_on" in bad.get_json()["error"]["fields"]
    assert (
        owner.post(
            "/promotions",
            {"name": "X", "promo_type": "multiplier", "multiplier_percent": 5000, "starts_on": "2026-10-01"},
        ).status_code
        == 422
    )
    staff = invite_and_join(owner, new_api, "staff")
    assert staff.get("/promotions").status_code == 200
    assert (
        staff.post(
            "/promotions", {"name": "X", "promo_type": "bonus", "bonus_points": 5, "starts_on": "2026-10-01"}
        ).status_code
        == 403
    )
    manager = invite_and_join(owner, new_api, "manager")
    assert (
        manager.post(
            "/promotions", {"name": "Mgr", "promo_type": "bonus", "bonus_points": 5, "starts_on": "2026-10-01"}
        ).status_code
        == 201
    )


def test_active_endpoint_reports_todays_promotions(owner):
    _promo(owner)
    with frozen_clock(TUESDAY_NOON_ET):
        assert [p["name"] for p in owner.get("/promotions/active").get_json()["data"]] == ["Double Tuesdays"]
    with frozen_clock(WEDNESDAY_NOON_ET):
        assert owner.get("/promotions/active").get_json()["data"] == []


# ------------------------------------------------------------------ birthdays


def test_birthday_validation(owner):
    assert (
        owner.post(
            "/customers", {"display_name": "A", "email": "a@x.io", "birth_month": 2, "birth_day": 30}
        ).status_code
        == 422
    )
    assert owner.post("/customers", {"display_name": "A", "email": "a@x.io", "birth_month": 2}).status_code == 422
    ok = owner.post("/customers", {"display_name": "A", "email": "a@x.io", "birth_month": 2, "birth_day": 29})
    assert ok.status_code == 201 and ok.get_json()["data"]["birth_day"] == 29


def test_birthday_bonus_once_per_year(owner):
    owner.patch("/programs/current", {"birthday_bonus_points": 100})
    bday = enroll(owner, "Birthday", birth_month=10, birth_day=20)
    other = enroll(owner, "Other", birth_month=10, birth_day=21)
    enroll(owner, "No birthday")
    business = db.session.get(Business, owner.business["id"])
    assert promotions.award_birthday_bonuses(business, now=TUESDAY_NOON_ET) == 1
    assert promotions.award_birthday_bonuses(business, now=TUESDAY_LATE_ET) == 0  # same local day, already awarded
    db.session.commit()
    assert db.session.get(Customer, bday["id"]).points_balance == 100
    assert db.session.get(Customer, other["id"]).points_balance == 0
    entry = PointLedgerEntry.query.filter_by(customer_id=bday["id"]).one()
    assert entry.entry_type == "birthday_bonus"
    # Next year it is awarded again.
    assert promotions.award_birthday_bonuses(business, now=datetime(2027, 10, 20, 16, 0)) == 1


def test_leap_day_birthdays_celebrated_on_feb_28(owner):
    owner.patch("/programs/current", {"birthday_bonus_points": 50})
    leap = enroll(owner, "Leap", birth_month=2, birth_day=29)
    business = db.session.get(Business, owner.business["id"])
    assert promotions.award_birthday_bonuses(business, now=datetime(2027, 2, 28, 17, 0)) == 1
    assert (
        promotions.award_birthday_bonuses(business, now=datetime(2028, 2, 28, 17, 0)) == 0
    )  # leap year: wait for 29th
    assert promotions.award_birthday_bonuses(business, now=datetime(2028, 2, 29, 17, 0)) == 1
    db.session.commit()
    assert db.session.get(Customer, leap["id"]).points_balance == 100


def test_birthday_bonus_off_by_default_and_cli(app, owner):
    enroll(owner, "B", birth_month=10, birth_day=20)
    business = db.session.get(Business, owner.business["id"])
    assert promotions.award_birthday_bonuses(business, now=TUESDAY_NOON_ET) == 0
    owner.patch("/programs/current", {"birthday_bonus_points": 25})
    with frozen_clock(TUESDAY_NOON_ET):
        result = app.test_cli_runner().invoke(args=["birthday-bonuses"])
    assert result.exit_code == 0 and "Awarded 1 birthday bonuses" in result.output


def test_portal_shows_promotions_and_customer_sets_birthday(owner, new_api):
    from .conftest import last_email_link, token_from

    _promo(owner, days_of_week=[])
    alice = enroll(owner, "Alice", email="alice.p@example.com")
    owner.post(f"/customers/{alice['id']}/portal-link")
    portal = new_api()
    portal.post(
        "/customer-portal/session", {"token": token_from(last_email_link("/portal/access", "alice.p@example.com"))}
    )
    me = portal.get("/customer-portal/me").get_json()["data"]
    assert [p["name"] for p in me["promotions"]] == ["Double Tuesdays"]
    assert portal.patch("/customer-portal/profile", {"birth_month": 4, "birth_day": 31}).status_code == 422
    assert (
        portal.patch("/customer-portal/profile", {"birth_month": 4, "birth_day": 30}).get_json()["data"]["birth_day"]
        == 30
    )
