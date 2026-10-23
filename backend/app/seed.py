"""Demo data. Every demo record is flagged ``is_demo`` and the business name says "(Demo)".

Refuses to run when APP_ENV=production or DEMO_MODE is off.
"""

import random
from datetime import timedelta
from types import SimpleNamespace

from flask import current_app
from sqlalchemy import delete

from .extensions import db
from .models import (
    Business,
    BusinessMembership,
    Location,
    LocationMembership,
    LoyaltyProgram,
    Reward,
    User,
    frozen_clock,
    utcnow,
)
from .security import hash_password
from .services import customers, purchases, redemptions, referrals

DEMO_PASSWORD = "DemoPass-2024!"
DEMO_USERS = [
    ("owner@demo.loyalloop.test", "Olivia Owner", "owner"),
    ("manager@demo.loyalloop.test", "Marcus Manager", "manager"),
    ("staff@demo.loyalloop.test", "Sam Staff", "staff"),
]
CUSTOMERS = [
    ("Ava Thompson", "ava.thompson@example.com", "+15035550101"),
    ("Liam Carter", "liam.carter@example.com", None),
    ("Sophia Nguyen", "sophia.nguyen@example.com", "+15035550103"),
    ("Noah Patel", "noah.patel@example.com", None),
    ("Isabella Garcia", "isabella.garcia@example.com", "+15035550105"),
    ("Mason Brooks", "mason.brooks@example.com", None),
    ("Mia Robinson", "mia.robinson@example.com", "+15035550107"),
    ("Ethan Rivera", "ethan.rivera@example.com", None),
    ("Harper Lee", "harper.lee@example.com", None),
    ("Lucas Kim", "lucas.kim@example.com", "+15035550110"),
    ("Amelia Scott", "amelia.scott@example.com", None),
    ("James Wilson", "james.wilson@example.com", None),
    ("Charlotte Davis", "charlotte.davis@example.com", "+15035550113"),
    ("Benjamin Moore", "benjamin.moore@example.com", None),
]


def _guard():
    if current_app.config["APP_ENV"] == "production" or not current_app.config["DEMO_MODE"]:
        raise SystemExit("Refusing to seed demo data: requires DEMO_MODE=true and APP_ENV != production")


def reset_demo():
    for business in Business.query.filter_by(is_demo=True).all():
        db.session.execute(delete(Business).where(Business.id == business.id))
    db.session.execute(delete(User).where(User.is_demo.is_(True)))  # includes the demo platform admin
    db.session.commit()


def seed(reset: bool = False, quiet: bool = False):
    _guard()
    if Business.query.filter_by(is_demo=True).first():
        if not reset:
            print("Demo data already exists. Use --reset to recreate it.")
            return
        reset_demo()
    elif reset:
        reset_demo()

    rng = random.Random(42)
    now = utcnow()
    start = now - timedelta(days=90)

    with frozen_clock(start - timedelta(days=1)):
        business = Business(
            name="Maple Street Coffee (Demo)",
            slug="maple-street-coffee-demo",
            is_demo=True,
            timezone="America/Los_Angeles",
            plan="growth",
            plan_status="active",
        )
        db.session.add(business)
        db.session.flush()
        downtown = Location(business_id=business.id, name="Downtown", address="120 SW Maple St, Portland, OR")
        eastside = Location(business_id=business.id, name="Eastside", address="2210 E Burnside St, Portland, OR")
        db.session.add_all([downtown, eastside])
        db.session.flush()
        users = {}
        for email, name, role in DEMO_USERS:
            user = User(
                email=email,
                display_name=name,
                password_hash=hash_password(DEMO_PASSWORD),
                email_verified_at=utcnow(),
                is_demo=True,
                timezone="America/Los_Angeles",
            )
            db.session.add(user)
            db.session.flush()
            membership = BusinessMembership(
                business_id=business.id, user_id=user.id, role=role, all_locations=role != "staff"
            )
            db.session.add(membership)
            db.session.flush()
            if role == "staff":
                db.session.add(LocationMembership(membership_id=membership.id, location_id=downtown.id))
            users[role] = user
        db.session.add(
            User(
                email="admin@demo.loyalloop.test",
                display_name="Pat Platform Admin",
                password_hash=hash_password(DEMO_PASSWORD),
                email_verified_at=utcnow(),
                is_demo=True,
                is_platform_admin=True,
            )
        )
        program = LoyaltyProgram(
            business_id=business.id,
            name="Maple Rewards",
            description="Earn points on every visit and trade them for drinks and treats.",
            brand_color="#1769aa",
            contact_email="hello@maple-demo.example.com",
            points_per_dollar=10,
            min_spend_cents=300,
            referrer_reward_points=150,
            referee_reward_points=75,
            referral_min_spend_cents=500,
            points_expiry_days=365,
        )
        rewards = [
            Reward(
                business_id=business.id,
                name="Free drip coffee",
                reward_type="free_item",
                points_cost=150,
                terms="Any size drip coffee.",
            ),
            Reward(
                business_id=business.id,
                name="$5 off your order",
                reward_type="fixed_discount",
                value_cents=500,
                points_cost=400,
                terms="Not combinable with other offers.",
            ),
            Reward(business_id=business.id, name="Free pastry", reward_type="free_item", points_cost=250),
            Reward(
                business_id=business.id,
                name="Bag of house beans",
                reward_type="custom",
                points_cost=1200,
                stock_limit=20,
                terms="While supplies last.",
            ),
        ]
        db.session.add(program)
        db.session.add_all(rewards)
        db.session.flush()

    tenant = SimpleNamespace(business_id=business.id)
    created = []
    for i, (name, email, phone) in enumerate(CUSTOMERS):
        enrolled = start + timedelta(days=rng.randint(0, 75), hours=rng.randint(7, 17))
        if i in (9, 11, 13):
            enrolled = max(enrolled, created[i - 9][1] + timedelta(days=2))
        location = downtown if i % 3 else eastside
        with frozen_clock(enrolled):
            customer = customers.enroll(
                business.id,
                name,
                email,
                phone,
                marketing_opt_in=(i % 2 == 0),
                source="staff",
                location_id=location.id,
                actor_id=users["staff"].id,
                is_demo=True,
            )
            if i in (9, 11, 13):  # referred by earlier customers
                referrals.attribute_signup(business.id, customer, created[i - 9][0].referral_code, source="staff")
        created.append((customer, enrolled, location))

    purchase_no = 1000
    for customer, enrolled, location in created:
        visits = rng.randint(2, 12)
        for _ in range(visits):
            at = enrolled + timedelta(days=rng.uniform(0, max(1, (now - enrolled).days - 1)))
            if at >= now:
                continue
            amount = rng.choice([450, 525, 680, 875, 1240, 1690, 2350])
            purchase_no += 1
            with frozen_clock(at):
                purchases.record_purchase(
                    tenant,
                    customer,
                    amount,
                    None,
                    location.id,
                    f"R-{purchase_no}",
                    f"seed-{purchase_no}",
                    users["staff"].id,
                )
    db.session.flush()

    # Some redemptions in different states.
    for idx, (customer, _, location) in enumerate(created[:6]):
        reward = rewards[0] if idx % 2 else rewards[2]
        if customer.points_balance < reward.points_cost:
            continue
        at = now - timedelta(days=rng.randint(1, 20))
        with frozen_clock(at):
            redemption, _ = redemptions.issue(
                business.id, customer, reward, f"seed-red-{idx}", actor_id=users["staff"].id, location_id=location.id
            )
        if idx < 4:
            with frozen_clock(at + timedelta(minutes=5)):
                redemptions.complete(
                    SimpleNamespace(business_id=business.id), redemption, location.id, users["staff"].id
                )

    # A pending (created) referral and a rejected self-referral attempt.
    with frozen_clock(now - timedelta(days=3)):
        referrals.create_invite(tenant, created[0][0], "friend.of.ava@example.com")
    db.session.commit()
    if not quiet:
        print("Demo data seeded for 'Maple Street Coffee (Demo)'.")
        for email, _, role in DEMO_USERS:
            print(f"  {role:<8} {email}  password: {DEMO_PASSWORD}")
        print(f"  {'admin':<8} admin@demo.loyalloop.test  password: {DEMO_PASSWORD}  (platform admin)")
