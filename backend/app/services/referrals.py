"""Referral attribution and qualification.

Lifecycle: created -> signed_up -> qualified -> rewarded, or -> rejected.
("clicked" exists in the schema for future link-click tracking; the MVP does
not record clicks, to avoid collecting data it does not need.)

A referral only becomes ``qualified`` from a purchase recorded server-side
by staff, so clients cannot self-qualify. Rewards are posted with idempotency
keys ``referral:<id>:referrer`` / ``referral:<id>:referee`` so they can never
be paid twice.
"""

from datetime import timedelta

from flask import current_app

from ..errors import Conflict, NotFound
from ..extensions import db
from ..models import Customer, LoyaltyProgram, Referral, utcnow
from . import audit, ledger


def find_referrer(business_id: int, code: str | None) -> Customer | None:
    if not code:
        return None
    return Customer.query.filter_by(
        business_id=business_id, referral_code=code.strip().upper(), status="active"
    ).first()


def attribute_signup(business_id: int, new_customer: Customer, code: str | None, source: str) -> Referral | None:
    """Attach a newly enrolled customer to a referrer. Invalid codes are ignored, abuse is recorded as rejected."""
    program = LoyaltyProgram.query.filter_by(business_id=business_id).first()
    if not code or not program or not program.referrals_enabled:
        return None
    referrer = find_referrer(business_id, code)
    if not referrer:
        return None

    pending = None
    if new_customer.email_normalized:
        pending = Referral.query.filter_by(
            business_id=business_id,
            referrer_customer_id=referrer.id,
            referred_email_normalized=new_customer.email_normalized,
            status="created",
            referred_customer_id=None,
        ).first()
    referral = pending or Referral(business_id=business_id, referrer_customer_id=referrer.id, source=source)
    referral.referred_customer_id = new_customer.id
    referral.referred_email_normalized = new_customer.email_normalized
    if not pending:
        db.session.add(referral)

    rejection = None
    if (
        referrer.id == new_customer.id
        or (referrer.email_normalized and referrer.email_normalized == new_customer.email_normalized)
        or (referrer.phone and referrer.phone == new_customer.phone)
    ):
        rejection = "Self-referral"
    else:
        since = utcnow() - timedelta(days=1)
        recent = Referral.query.filter(
            Referral.referrer_customer_id == referrer.id,
            Referral.signed_up_at >= since,
        ).count()
        if recent >= current_app.config["REFERRAL_DAILY_SIGNUP_LIMIT"]:
            rejection = "Referrer exceeded the daily referral limit"

    if rejection:
        referral.status = "rejected"
        referral.rejection_reason = rejection
    else:
        referral.status = "signed_up"
        referral.signed_up_at = utcnow()
    db.session.flush()
    return referral


def create_invite(tenant, referrer: Customer, email: str) -> Referral:
    """Staff record that a customer referred a friend who has not enrolled yet."""
    if referrer.status != "active":
        raise Conflict("Only active customers can refer friends")
    if referrer.email_normalized == email:
        raise Conflict("Customers cannot refer themselves", code="self_referral")
    if Customer.query.filter_by(business_id=tenant.business_id, email_normalized=email).first():
        raise Conflict("That person is already enrolled, so the referral cannot be attributed", code="already_customer")
    existing = Referral.query.filter_by(
        business_id=tenant.business_id, referred_email_normalized=email, referred_customer_id=None, status="created"
    ).first()
    if existing:
        raise Conflict("A pending referral already exists for this email", code="duplicate_referral")
    referral = Referral(
        business_id=tenant.business_id,
        referrer_customer_id=referrer.id,
        referred_email_normalized=email,
        status="created",
        source="staff",
    )
    db.session.add(referral)
    db.session.flush()
    return referral


def on_purchase(program: LoyaltyProgram, customer: Customer, purchase, actor_id) -> Referral | None:
    referral = Referral.query.filter_by(
        business_id=customer.business_id, referred_customer_id=customer.id, status="signed_up"
    ).first()
    if not referral or purchase.eligible_cents < program.referral_min_spend_cents:
        return None
    referral.status = "qualified"
    referral.qualified_at = utcnow()
    referral.qualifying_purchase_id = purchase.id
    if program.referrals_enabled and program.status == "active":
        reward(program, referral, actor_id, location_id=purchase.location_id)
    return referral


def reward(program: LoyaltyProgram, referral: Referral, actor_id, location_id=None) -> None:
    if referral.status != "qualified":
        raise Conflict("Only qualified referrals can be rewarded")
    referrer = referral.referrer
    if program.referrer_reward_points and referrer.status == "active":
        key = f"referral:{referral.id}:referrer"
        if not ledger.find_by_key(referral.business_id, key):
            ledger.post_entry(
                referrer,
                program.referrer_reward_points,
                "referral_bonus",
                reason="Referral reward: friend made a qualifying purchase",
                location_id=location_id,
                source_type="referral",
                source_id=referral.id,
                actor_id=actor_id,
                idempotency_key=key,
            )
    referred = referral.referred
    if program.referee_reward_points and referred and referred.status == "active":
        key = f"referral:{referral.id}:referee"
        if not ledger.find_by_key(referral.business_id, key):
            ledger.post_entry(
                referred,
                program.referee_reward_points,
                "referral_bonus",
                reason="Welcome reward for joining through a referral",
                location_id=location_id,
                source_type="referral",
                source_id=referral.id,
                actor_id=actor_id,
                idempotency_key=key,
            )
    referral.status = "rewarded"
    referral.rewarded_at = utcnow()


def get_referral(business_id: int, referral_id: int) -> Referral:
    referral = Referral.query.filter_by(id=referral_id, business_id=business_id).first()
    if not referral:
        raise NotFound("Referral not found")
    return referral


def reject(tenant, referral: Referral, reason: str) -> None:
    if referral.status in ("rewarded", "rejected"):
        raise Conflict(f"A {referral.status} referral cannot be rejected", code="invalid_transition")
    referral.status = "rejected"
    referral.rejection_reason = reason
    audit.record(
        "referral.rejected",
        business_id=tenant.business_id,
        target_type="referral",
        target_id=referral.id,
        reason=reason,
    )
