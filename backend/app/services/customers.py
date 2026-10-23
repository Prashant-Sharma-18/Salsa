from sqlalchemy import or_

from ..errors import Conflict, NotFound
from ..extensions import db
from ..models import (
    ConsentRecord,
    Customer,
    CustomerAccessToken,
    CustomerSession,
    PointLedgerEntry,
    Purchase,
    Redemption,
    Referral,
    utcnow,
)
from ..security import random_code
from . import audit


def get_customer(business_id: int, customer_id: int) -> Customer:
    customer = Customer.query.filter_by(id=customer_id, business_id=business_id).first()
    if not customer:
        raise NotFound("Customer not found")
    return customer


def find_by_email(business_id: int, email: str | None) -> Customer | None:
    if not email:
        return None
    return Customer.query.filter_by(business_id=business_id, email_normalized=email).first()


def unique_referral_code() -> str:
    while True:
        code = random_code(8)
        if not Customer.query.filter_by(referral_code=code).first():
            return code


def enroll(
    business_id: int,
    display_name: str,
    email: str | None,
    phone: str | None,
    marketing_opt_in: bool,
    source: str,
    location_id=None,
    actor_id=None,
    is_demo=False,
) -> Customer:
    """Create a customer. Email (already normalised) must be unique within the business."""
    if email and find_by_email(business_id, email):
        raise Conflict("A customer with this email is already enrolled", code="duplicate_customer")
    customer = Customer(
        business_id=business_id,
        display_name=display_name,
        email=email,
        email_normalized=email,
        phone=phone,
        enrolled_location_id=location_id,
        referral_code=unique_referral_code(),
        marketing_opt_in=bool(marketing_opt_in),
        is_demo=is_demo,
    )
    db.session.add(customer)
    db.session.flush()
    if marketing_opt_in:
        db.session.add(
            ConsentRecord(
                business_id=business_id,
                customer_id=customer.id,
                granted=True,
                source=source,
                actor_user_id=actor_id,
            )
        )
    return customer


def set_marketing_consent(customer: Customer, granted: bool, source: str, actor_id=None) -> None:
    if customer.marketing_opt_in == granted:
        return
    customer.marketing_opt_in = granted
    db.session.add(
        ConsentRecord(
            business_id=customer.business_id,
            customer_id=customer.id,
            granted=granted,
            source=source,
            actor_user_id=actor_id,
        )
    )


def search(business_id: int, q: str | None = None, status: str | None = None):
    query = Customer.query.filter(Customer.business_id == business_id)
    if status:
        query = query.filter(Customer.status == status)
    if q:
        term = f"%{q.strip().lower()}%"
        digits = "".join(ch for ch in q if ch.isdigit())
        conditions = [
            Customer.display_name.ilike(term),
            Customer.email_normalized.like(term),
            Customer.referral_code == q.strip().upper(),
        ]
        if len(digits) >= 4:
            conditions.append(Customer.phone.like(f"%{digits}%"))
        query = query.filter(or_(*conditions))
    return query.order_by(Customer.enrolled_at.desc(), Customer.id.desc())


def privacy_export(customer: Customer) -> dict:
    """Everything the business holds about a customer, for access requests."""
    return {
        "customer": customer.to_dict(detail=True),
        "consent_history": [
            c.to_dict() for c in ConsentRecord.query.filter_by(customer_id=customer.id).order_by(ConsentRecord.id)
        ],
        "ledger": [
            e.to_dict() for e in PointLedgerEntry.query.filter_by(customer_id=customer.id).order_by(PointLedgerEntry.id)
        ],
        "purchases": [p.to_dict() for p in Purchase.query.filter_by(customer_id=customer.id).order_by(Purchase.id)],
        "redemptions": [
            r.to_dict(include_customer=False)
            for r in Redemption.query.filter_by(customer_id=customer.id).order_by(Redemption.id)
        ],
        "referrals_made": [r.to_dict() for r in Referral.query.filter_by(referrer_customer_id=customer.id)],
        "exported_at": utcnow().isoformat() + "Z",
    }


def anonymize(tenant, customer: Customer, actor_id: int) -> None:
    """Deletion workflow: remove personal data but keep the anonymous ledger for financial integrity."""
    if customer.status == "anonymized":
        raise Conflict("Customer is already anonymized")
    customer.display_name = f"Deleted customer #{customer.id}"
    customer.email = None
    customer.email_normalized = None
    customer.phone = None
    customer.marketing_opt_in = False
    customer.status = "anonymized"
    customer.anonymized_at = utcnow()
    Referral.query.filter_by(referrer_customer_id=customer.id).update({"referred_email_normalized": None})
    now = utcnow()
    CustomerSession.query.filter_by(customer_id=customer.id, revoked_at=None).update({"revoked_at": now})
    CustomerAccessToken.query.filter_by(customer_id=customer.id, used_at=None).update({"used_at": now})
    Redemption.query.filter_by(customer_id=customer.id, status="issued").update(
        {"status": "cancelled", "cancelled_at": now, "cancel_reason": "Customer data deleted"}
    )
    audit.record("customer.anonymized", business_id=tenant.business_id, target_type="customer", target_id=customer.id)
