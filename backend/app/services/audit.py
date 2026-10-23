from flask import g

from ..extensions import db
from ..models import AuditLog


def record(action: str, business_id=None, target_type=None, target_id=None, actor_id=None, **details):
    """Add an audit entry to the current transaction. Never include secrets or full contact details."""
    if actor_id is None:
        user = g.get("user")
        actor_id = user.id if user else None
    db.session.add(
        AuditLog(
            business_id=business_id,
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )
