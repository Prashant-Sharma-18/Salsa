"""Reward redemption.

Status transitions (enforced here, server-side)::

    issued -> redeemed   staff validated the code at checkout
    issued -> cancelled  points refunded via a reversal ledger entry
    issued -> expired    code not used before expires_at; points refunded

Redeemed, cancelled and expired are terminal.
"""

from flask import current_app
from sqlalchemy import or_, update

from ..errors import ApiError, Conflict, NotFound
from ..extensions import db
from ..models import LoyaltyProgram, Redemption, Reward, utcnow
from ..security import random_code
from . import audit, ledger

TRANSITIONS = {"issued": {"redeemed", "cancelled", "expired"}}


def _transition(redemption: Redemption, new_status: str):
    if new_status not in TRANSITIONS.get(redemption.status, set()):
        raise Conflict(
            f"This code is already {redemption.status} and cannot be marked {new_status}.", code="invalid_transition"
        )
    redemption.status = new_status


def _unique_code() -> str:
    while True:
        code = random_code(8)
        if not Redemption.query.filter_by(code=code).first():
            return code


def issue(business_id, customer, reward: Reward, idempotency_key: str, actor_id=None, location_id=None, via="staff"):
    """Atomically check balance and stock, debit points, and create a unique redemption code."""
    existing = Redemption.query.filter_by(business_id=business_id, idempotency_key=idempotency_key).first()
    if existing:
        if existing.customer_id != customer.id or existing.reward_id != reward.id:
            raise Conflict("This request key was already used for a different redemption", code="idempotency_mismatch")
        return existing, True

    program = LoyaltyProgram.query.filter_by(business_id=business_id).one()
    if program.status != "active" or not program.redemption_enabled:
        raise Conflict("Redemptions are currently turned off for this program", code="redemption_disabled")
    if reward.business_id != business_id or reward.status != "active":
        raise NotFound("Reward not available")
    if customer.status != "active":
        raise Conflict("Only active customers can redeem rewards")
    if customer.points_balance < reward.points_cost:
        raise ledger.InsufficientPoints(
            f"Not enough points: {reward.name} costs {reward.points_cost} and the balance is {customer.points_balance}."
        )

    stock = db.session.execute(
        update(Reward)
        .where(
            Reward.id == reward.id,
            or_(Reward.stock_limit.is_(None), Reward.stock_redeemed < Reward.stock_limit),
        )
        .values(stock_redeemed=Reward.stock_redeemed + 1)
        .execution_options(synchronize_session=False)
    )
    if stock.rowcount != 1:
        raise ApiError("This reward is out of stock", code="out_of_stock", status=409)
    db.session.expire(reward, ["stock_redeemed"])

    redemption = Redemption(
        business_id=business_id,
        customer_id=customer.id,
        reward_id=reward.id,
        location_id=location_id,
        code=_unique_code(),
        points_cost=reward.points_cost,
        idempotency_key=idempotency_key,
        issued_by_id=actor_id,
        issued_via=via,
        expires_at=utcnow() + current_app.config["REDEMPTION_CODE_TTL"],
    )
    db.session.add(redemption)
    db.session.flush()
    entry = ledger.post_entry(
        customer,
        -reward.points_cost,
        "redemption",
        reason=f"Redeemed: {reward.name}",
        location_id=location_id,
        source_type="redemption",
        source_id=redemption.id,
        actor_id=actor_id,
        idempotency_key=f"redemption:{redemption.id}",
    )
    redemption.ledger_entry_id = entry.id
    audit.record(
        "redemption.issued",
        business_id=business_id,
        actor_id=actor_id,
        target_type="redemption",
        target_id=redemption.id,
        reward_id=reward.id,
        points=reward.points_cost,
        via=via,
    )
    return redemption, False


def _refund(redemption: Redemption, reason: str, actor_id):
    from ..models import PointLedgerEntry

    original = db.session.get(PointLedgerEntry, redemption.ledger_entry_id)
    ledger.post_entry(
        redemption.customer,
        redemption.points_cost,
        "reversal",
        reason=reason,
        location_id=redemption.location_id,
        source_type="redemption",
        source_id=redemption.id,
        actor_id=actor_id,
        idempotency_key=f"redemption-refund:{redemption.id}",
        reverses_entry_id=original.id if original else None,
    )
    db.session.execute(
        update(Reward)
        .where(Reward.id == redemption.reward_id, Reward.stock_redeemed > 0)
        .values(stock_redeemed=Reward.stock_redeemed - 1)
        .execution_options(synchronize_session=False)
    )


def find_by_code(business_id: int, code: str) -> Redemption:
    redemption = Redemption.query.filter_by(business_id=business_id, code=code.strip().upper()).first()
    if not redemption:
        raise NotFound("No redemption found with that code")
    return redemption


def expire_if_due(redemption: Redemption, actor_id=None) -> bool:
    if redemption.status == "issued" and redemption.expires_at < utcnow():
        _transition(redemption, "expired")
        if redemption.customer.status != "anonymized":
            _refund(redemption, "Unused redemption code expired; points returned", actor_id)
        return True
    return False


def complete(tenant, redemption: Redemption, location_id: int, actor_id: int) -> Redemption:
    if expire_if_due(redemption, actor_id):
        db.session.commit()
        raise Conflict("This code has expired. The points were returned to the customer.", code="code_expired")
    _transition(redemption, "redeemed")
    redemption.completed_at = utcnow()
    redemption.completed_by_id = actor_id
    redemption.completed_location_id = location_id
    audit.record(
        "redemption.completed",
        business_id=tenant.business_id,
        target_type="redemption",
        target_id=redemption.id,
        location_id=location_id,
    )
    return redemption


def cancel(tenant, redemption: Redemption, reason: str, actor_id: int) -> Redemption:
    _transition(redemption, "cancelled")
    redemption.cancelled_at = utcnow()
    redemption.cancel_reason = reason
    _refund(redemption, f"Redemption cancelled: {reason}", actor_id)
    audit.record(
        "redemption.cancelled",
        business_id=tenant.business_id,
        target_type="redemption",
        target_id=redemption.id,
        reason=reason,
    )
    return redemption


def expire_stale(business_id: int) -> int:
    count = 0
    for redemption in Redemption.query.filter(
        Redemption.business_id == business_id, Redemption.status == "issued", Redemption.expires_at < utcnow()
    ):
        if expire_if_due(redemption):
            count += 1
    return count
