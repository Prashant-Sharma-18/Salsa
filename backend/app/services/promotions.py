"""Promotions and birthday bonuses.

Purchase promotions only apply to purchases that already earn points:
- multiplier promotions: the single best multiplier applies (no stacking),
  extra = floor(base * (multiplier - 100) / 100);
- bonus promotions: every applicable bonus is added.
Dates and weekdays use the business's local time zone.
"""

import calendar
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..extensions import db
from ..models import Business, Customer, LoyaltyProgram, Promotion, utcnow
from . import audit, ledger


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_today(business: Business, now: datetime | None = None) -> date:
    moment = (now or utcnow()).replace(tzinfo=timezone.utc)
    return moment.astimezone(_tz(business.timezone)).date()


def applicable(business: Business, location_id: int | None, eligible_cents: int, on: date) -> list[Promotion]:
    promos = Promotion.query.filter(
        Promotion.business_id == business.id,
        Promotion.status == "active",
        Promotion.starts_on <= on,
        (Promotion.ends_on.is_(None)) | (Promotion.ends_on >= on),
    ).all()
    result = []
    for p in promos:
        if p.days_of_week and on.weekday() not in p.days_of_week:
            continue
        if p.location_ids and location_id not in p.location_ids:
            continue
        if eligible_cents < (p.min_spend_cents or 0):
            continue
        result.append(p)
    return result


def compute(base_points: int, promos: list[Promotion]) -> tuple[int, list[dict]]:
    """Return (extra points, applied promotions) for a purchase's base points."""
    if base_points <= 0 or not promos:
        return 0, []
    applied: list[dict] = []
    extra = 0
    multipliers = [p for p in promos if p.promo_type == "multiplier" and p.multiplier_percent]
    if multipliers:
        best = max(multipliers, key=lambda p: (p.multiplier_percent, -p.id))
        points = base_points * (best.multiplier_percent - 100) // 100
        if points:
            extra += points
            applied.append({"id": best.id, "name": best.name, "points": points})
    for p in sorted((p for p in promos if p.promo_type == "bonus" and p.bonus_points), key=lambda p: p.id):
        extra += p.bonus_points
        applied.append({"id": p.id, "name": p.name, "points": p.bonus_points})
    return extra, applied


# ------------------------------------------------------------------ birthdays


def _is_birthday(customer: Customer, today: date) -> bool:
    if not customer.birth_month or not customer.birth_day:
        return False
    month, day = customer.birth_month, customer.birth_day
    if month == 2 and day == 29 and not calendar.isleap(today.year):
        day = 28  # Feb 29 birthdays are celebrated on Feb 28 in non-leap years
    return (today.month, today.day) == (month, day)


def award_birthday_bonuses(business: Business, now: datetime | None = None) -> int:
    """Award today's birthday bonuses for one business. Safe to run repeatedly (once per customer per year)."""
    from ..email import link, queue_email

    program = LoyaltyProgram.query.filter_by(business_id=business.id).first()
    if (
        not program
        or not program.birthday_bonus_points
        or program.status != "active"
        or not program.earning_enabled
        or business.suspended_at
    ):
        return 0
    from .. import billing

    if not billing.in_good_standing(business):
        return 0
    today = local_today(business, now)
    candidates = Customer.query.filter(
        Customer.business_id == business.id,
        Customer.status == "active",
        Customer.birth_month == today.month,
        Customer.birth_day.in_([today.day, 29] if (today.month, today.day) == (2, 28) else [today.day]),
    ).all()
    awarded = 0
    for customer in candidates:
        if not _is_birthday(customer, today):
            continue
        key = f"birthday:{customer.id}:{today.year}"
        if ledger.find_by_key(business.id, key):
            continue
        ledger.post_entry(
            customer,
            program.birthday_bonus_points,
            "birthday_bonus",
            reason="Happy birthday!",
            source_type="birthday",
            idempotency_key=key,
        )
        if customer.email and customer.marketing_opt_in:
            queue_email(
                "birthday_bonus",
                customer.email,
                f"Happy birthday from {business.name}!",
                f"We've added {program.birthday_bonus_points} bonus points to your {program.name} account.\n\n"
                f"See your rewards: {link('/portal/' + business.slug)}\n",
                business_id=business.id,
                dedupe_key=key,
            )
        awarded += 1
    if awarded:
        audit.record("points.birthday_bonuses", business_id=business.id, actor_id=None, customers=awarded)
    db.session.flush()
    return awarded
