from sqlalchemy.exc import IntegrityError

from ..errors import Conflict, ValidationError
from ..extensions import db
from ..models import LoyaltyProgram, Purchase
from . import ledger, referrals


def points_for(program: LoyaltyProgram, eligible_cents: int) -> int:
    """Integer points: floor(eligible dollars * points_per_dollar). No floating point."""
    if program.status != "active" or not program.earning_enabled:
        return 0
    if eligible_cents < program.min_spend_cents:
        return 0
    return (eligible_cents * program.points_per_dollar) // 100


def record_purchase(
    tenant,
    customer,
    amount_cents: int,
    eligible_cents: int | None,
    location_id: int,
    external_ref: str | None,
    idempotency_key: str,
    actor_id: int,
) -> tuple[Purchase, bool]:
    """Record a purchase and award points in one transaction. Returns (purchase, was_duplicate)."""
    business_id = tenant.business_id
    if eligible_cents is None:
        eligible_cents = amount_cents
    if eligible_cents > amount_cents:
        raise ValidationError(
            "Eligible amount cannot exceed the purchase total", fields={"eligible_amount": "Too high"}
        )
    if customer.status != "active":
        raise Conflict("Points can only be awarded to active customers")

    existing = Purchase.query.filter_by(business_id=business_id, idempotency_key=idempotency_key).first()
    if existing:
        if existing.customer_id != customer.id or existing.amount_cents != amount_cents:
            raise Conflict("This request key was already used for a different purchase", code="idempotency_mismatch")
        return existing, True
    if external_ref and Purchase.query.filter_by(business_id=business_id, external_ref=external_ref).first():
        raise Conflict(
            f"Receipt {external_ref} has already been recorded. Points were not awarded twice.",
            code="duplicate_transaction",
        )

    program = LoyaltyProgram.query.filter_by(business_id=business_id).one()
    points = points_for(program, eligible_cents)
    purchase = Purchase(
        business_id=business_id,
        customer_id=customer.id,
        location_id=location_id,
        amount_cents=amount_cents,
        eligible_cents=eligible_cents,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        points_awarded=points,
        created_by_id=actor_id,
    )
    try:
        with db.session.begin_nested():
            db.session.add(purchase)
            db.session.flush()
    except IntegrityError:
        # A concurrent request with the same key/receipt won the race.
        raise Conflict(
            "This purchase was already recorded. Points were not awarded twice.", code="duplicate_transaction"
        )

    if points:
        ledger.post_entry(
            customer,
            points,
            "award",
            reason=f"Purchase ${amount_cents / 100:,.2f}" + (f" (receipt {external_ref})" if external_ref else ""),
            location_id=location_id,
            source_type="purchase",
            source_id=purchase.id,
            actor_id=actor_id,
            idempotency_key=f"purchase:{purchase.id}",
        )
    referrals.on_purchase(program, customer, purchase, actor_id)
    return purchase, False
