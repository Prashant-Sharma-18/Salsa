"""Analytics computed directly from database rows.

Metric definitions (all within [start, end) in UTC; location filter applies
where a row has a location):

- enrollments: customers whose enrollment time falls in the range (location = enrolling location).
- active_customers: distinct customers with at least one award, redemption or referral bonus entry in range.
- points_issued: sum of positive award, referral_bonus and adjustment entries.
- points_redeemed: points debited for reward redemptions, minus points refunded for cancelled/expired redemptions.
- rewards_redeemed: redemptions completed (status redeemed) in range, by completion location.
- referrals: referrals that signed up in range.
- qualified_referrals: referrals that reached qualified or rewarded in range (by qualification time).
"""

from datetime import datetime, timedelta

from sqlalchemy import and_, false, func, or_, select, true

from ..extensions import db
from ..models import Customer, PointLedgerEntry, Redemption, Referral

DEFINITIONS = {
    "enrollments": "Customers enrolled during the period.",
    "active_customers": "Distinct customers who earned, redeemed or received a referral bonus during the period.",
    "points_issued": "Points added through purchases, referral bonuses and positive manual adjustments.",
    "points_redeemed": "Points spent on rewards, net of refunds for cancelled or expired codes.",
    "rewards_redeemed": "Reward codes validated and completed by staff during the period.",
    "referrals": "Referred friends who enrolled during the period.",
    "qualified_referrals": "Referrals whose friend made a qualifying purchase during the period.",
}


def _loc(column, location_ids):
    if location_ids is None:
        return true()
    return column.in_(location_ids) if location_ids else false()


def summary(business_id: int, start: datetime, end: datetime, location_ids: list[int] | None) -> dict:
    L = PointLedgerEntry
    in_range = and_(
        L.business_id == business_id, L.created_at >= start, L.created_at < end, _loc(L.location_id, location_ids)
    )

    enrollments = db.session.scalar(
        select(func.count(Customer.id)).where(
            Customer.business_id == business_id,
            Customer.enrolled_at >= start,
            Customer.enrolled_at < end,
            _loc(Customer.enrolled_location_id, location_ids),
        )
    )
    active = db.session.scalar(
        select(func.count(func.distinct(L.customer_id))).where(
            in_range, L.entry_type.in_(("award", "redemption", "referral_bonus"))
        )
    )
    issued = db.session.scalar(
        select(func.coalesce(func.sum(L.points), 0)).where(
            in_range, L.points > 0, L.entry_type.in_(("award", "referral_bonus", "adjustment"))
        )
    )
    debited = db.session.scalar(
        select(func.coalesce(func.sum(L.points), 0)).where(in_range, L.entry_type == "redemption")
    )
    refunded = db.session.scalar(
        select(func.coalesce(func.sum(L.points), 0)).where(
            in_range, L.entry_type == "reversal", L.source_type == "redemption"
        )
    )
    rewards_redeemed = db.session.scalar(
        select(func.count(Redemption.id)).where(
            Redemption.business_id == business_id,
            Redemption.status == "redeemed",
            Redemption.completed_at >= start,
            Redemption.completed_at < end,
            _loc(Redemption.completed_location_id, location_ids),
        )
    )
    referrals = db.session.scalar(
        select(func.count(Referral.id)).where(
            Referral.business_id == business_id, Referral.signed_up_at >= start, Referral.signed_up_at < end
        )
    )
    qualified = db.session.scalar(
        select(func.count(Referral.id)).where(
            Referral.business_id == business_id,
            Referral.qualified_at >= start,
            Referral.qualified_at < end,
            or_(Referral.status == "qualified", Referral.status == "rewarded"),
        )
    )
    return {
        "enrollments": int(enrollments or 0),
        "active_customers": int(active or 0),
        "points_issued": int(issued or 0),
        "points_redeemed": int(-(debited or 0) - (refunded or 0)),
        "rewards_redeemed": int(rewards_redeemed or 0),
        "referrals": int(referrals or 0),
        "qualified_referrals": int(qualified or 0),
    }


def daily_series(business_id: int, start: datetime, end: datetime, location_ids: list[int] | None) -> list[dict]:
    """Per-day points issued/redeemed and enrollments. Grouped in Python for SQLite/PostgreSQL portability."""
    days: dict[str, dict] = {}
    cursor = start
    while cursor < end and len(days) < 400:
        days[cursor.date().isoformat()] = {
            "date": cursor.date().isoformat(),
            "points_issued": 0,
            "points_redeemed": 0,
            "enrollments": 0,
        }
        cursor += timedelta(days=1)

    L = PointLedgerEntry
    rows = db.session.execute(
        select(L.created_at, L.entry_type, L.points, L.source_type).where(
            L.business_id == business_id, L.created_at >= start, L.created_at < end, _loc(L.location_id, location_ids)
        )
    )
    for created_at, entry_type, points, source_type in rows:
        day = days.get(created_at.date().isoformat())
        if not day:
            continue
        if entry_type in ("award", "referral_bonus", "adjustment") and points > 0:
            day["points_issued"] += points
        elif entry_type == "redemption":
            day["points_redeemed"] += -points
        elif entry_type == "reversal" and source_type == "redemption":
            day["points_redeemed"] -= points

    for (enrolled_at,) in db.session.execute(
        select(Customer.enrolled_at).where(
            Customer.business_id == business_id,
            Customer.enrolled_at >= start,
            Customer.enrolled_at < end,
            _loc(Customer.enrolled_location_id, location_ids),
        )
    ):
        day = days.get(enrolled_at.date().isoformat())
        if day:
            day["enrollments"] += 1
    return list(days.values())
