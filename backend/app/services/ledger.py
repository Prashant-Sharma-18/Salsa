"""Points ledger.

Balance strategy: ``customers.points_balance`` is a cached balance updated in
the same transaction as each ledger insert using a guarded atomic UPDATE::

    UPDATE customers SET points_balance = points_balance + :delta
    WHERE id = :id AND business_id = :bid AND points_balance + :delta >= 0

If no row is updated the operation would overdraw the balance and is rejected.
This is safe under concurrency on PostgreSQL (row lock taken by UPDATE) and on
SQLite (database-level write lock). A CHECK constraint (balance >= 0) is a
second line of defence. ``reconcile`` compares the cache with SUM(ledger.points).
"""

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm.attributes import set_committed_value

from ..errors import ApiError, Conflict, NotFound, ValidationError
from ..extensions import db
from ..models import Customer, LoyaltyProgram, PointLedgerEntry, Purchase, utcnow
from . import audit

ACTIVITY_TYPES = {"award", "redemption", "referral_bonus"}


class InsufficientPoints(ApiError):
    status = 409
    code = "insufficient_points"


def find_by_key(business_id: int, key: str | None) -> PointLedgerEntry | None:
    if not key:
        return None
    return PointLedgerEntry.query.filter_by(business_id=business_id, idempotency_key=key).first()


def post_entry(
    customer: Customer,
    points: int,
    entry_type: str,
    reason: str = "",
    location_id=None,
    source_type=None,
    source_id=None,
    actor_id=None,
    idempotency_key=None,
    reverses_entry_id=None,
) -> PointLedgerEntry:
    """Append a ledger entry and update the cached balance atomically (caller commits)."""
    if points == 0:
        raise ValidationError("Points must not be zero")
    if customer.status == "anonymized":
        raise Conflict("This customer record has been anonymized")
    values = {"points_balance": Customer.points_balance + points}
    if entry_type in ACTIVITY_TYPES:
        values["last_activity_at"] = utcnow()
    result = db.session.execute(
        update(Customer)
        .where(
            Customer.id == customer.id,
            Customer.business_id == customer.business_id,
            Customer.points_balance + points >= 0,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise InsufficientPoints("The customer does not have enough points for this.")
    new_balance = db.session.execute(select(Customer.points_balance).where(Customer.id == customer.id)).scalar_one()
    set_committed_value(customer, "points_balance", new_balance)
    if "last_activity_at" in values:
        db.session.expire(customer, ["last_activity_at"])
    entry = PointLedgerEntry(
        business_id=customer.business_id,
        customer_id=customer.id,
        location_id=location_id,
        entry_type=entry_type,
        points=points,
        balance_after=new_balance,
        reason=reason[:255],
        source_type=source_type,
        source_id=source_id,
        actor_user_id=actor_id,
        idempotency_key=idempotency_key,
        reverses_entry_id=reverses_entry_id,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def adjust(tenant, customer: Customer, points: int, reason: str, actor_id: int, location_id=None) -> PointLedgerEntry:
    if not reason or len(reason.strip()) < 3:
        raise ValidationError("A reason is required for manual adjustments", fields={"reason": "Required"})
    entry = post_entry(
        customer,
        points,
        "adjustment",
        reason=reason.strip(),
        location_id=location_id,
        source_type="manual",
        actor_id=actor_id,
    )
    audit.record(
        "points.adjusted",
        business_id=tenant.business_id,
        target_type="customer",
        target_id=customer.id,
        points=points,
        reason=reason.strip(),
        ledger_entry_id=entry.id,
    )
    return entry


def reverse(tenant, entry: PointLedgerEntry, reason: str, actor_id: int) -> PointLedgerEntry:
    if not reason or len(reason.strip()) < 3:
        raise ValidationError("A reason is required for reversals", fields={"reason": "Required"})
    if entry.entry_type == "reversal":
        raise Conflict("A reversal cannot itself be reversed. Use a manual adjustment instead.")
    if entry.entry_type == "redemption":
        raise Conflict("Cancel the redemption instead; that refunds the points and updates its status.")
    if PointLedgerEntry.query.filter_by(reverses_entry_id=entry.id).first():
        raise Conflict("This entry has already been reversed", code="already_reversed")
    customer = db.session.get(Customer, entry.customer_id)
    try:
        reversal = post_entry(
            customer,
            -entry.points,
            "reversal",
            reason=reason.strip(),
            location_id=entry.location_id,
            source_type="ledger",
            source_id=entry.id,
            actor_id=actor_id,
            idempotency_key=f"reverse:{entry.id}",
            reverses_entry_id=entry.id,
        )
    except InsufficientPoints:
        raise InsufficientPoints(
            "The customer has already spent some of these points, so a full reversal would make the balance "
            "negative. Use a manual adjustment for the remaining amount."
        )
    if entry.source_type == "purchase" and entry.source_id:
        purchase = db.session.get(Purchase, entry.source_id)
        if purchase:
            purchase.status = "reversed"
    audit.record(
        "points.reversed",
        business_id=tenant.business_id,
        target_type="ledger_entry",
        target_id=entry.id,
        points=-entry.points,
        reason=reason.strip(),
    )
    return reversal


def get_entry(business_id: int, entry_id: int) -> PointLedgerEntry:
    entry = PointLedgerEntry.query.filter_by(id=entry_id, business_id=business_id).first()
    if not entry:
        raise NotFound("Ledger entry not found")
    return entry


def reconcile(business_id: int, customer_id: int | None = None) -> list[dict]:
    """Return customers whose cached balance differs from the ledger sum (empty list = consistent)."""
    ledger_sum = (
        select(PointLedgerEntry.customer_id, func.coalesce(func.sum(PointLedgerEntry.points), 0).label("total"))
        .where(PointLedgerEntry.business_id == business_id)
        .group_by(PointLedgerEntry.customer_id)
        .subquery()
    )
    query = (
        select(Customer.id, Customer.points_balance, func.coalesce(ledger_sum.c.total, 0))
        .outerjoin(ledger_sum, ledger_sum.c.customer_id == Customer.id)
        .where(Customer.business_id == business_id)
    )
    if customer_id:
        query = query.where(Customer.id == customer_id)
    return [
        {"customer_id": cid, "cached_balance": cached, "ledger_balance": int(total)}
        for cid, cached, total in db.session.execute(query)
        if cached != int(total)
    ]


def process_expirations(business_id: int, actor_id=None, now=None) -> int:
    """Expire balances of customers inactive longer than the program's expiry window.

    Policy: inactivity expiry. Earning, redeeming or receiving a referral bonus
    counts as activity. The idempotency key includes the last activity time,
    so re-running never expires the same balance twice.
    """
    program = LoyaltyProgram.query.filter_by(business_id=business_id).first()
    if not program or not program.points_expiry_days:
        return 0
    now = now or utcnow()
    cutoff = now - timedelta(days=program.points_expiry_days)
    customers = Customer.query.filter(
        Customer.business_id == business_id,
        Customer.points_balance > 0,
        Customer.last_activity_at < cutoff,
        Customer.status != "anonymized",
    ).all()
    count = 0
    for customer in customers:
        key = f"expire:{customer.id}:{customer.last_activity_at.isoformat()}"
        if find_by_key(business_id, key):
            continue
        post_entry(
            customer,
            -customer.points_balance,
            "expiration",
            reason=f"No activity for {program.points_expiry_days} days",
            source_type="expiry",
            actor_id=actor_id,
            idempotency_key=key,
        )
        count += 1
    if count:
        audit.record("points.expired", business_id=business_id, actor_id=actor_id, customers=count)
    return count
