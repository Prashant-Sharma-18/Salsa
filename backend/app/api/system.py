from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..errors import NotFound
from ..extensions import db
from ..models import Business, NotificationOutbox

bp = Blueprint("system", __name__)


@bp.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    status = 200 if database == "ok" else 503
    return jsonify({"status": "ok" if status == 200 else "degraded", "database": database}), status


@bp.get("/meta")
def meta():
    cfg = current_app.config
    demo = cfg["DEMO_MODE"] and cfg["APP_ENV"] != "production"
    return jsonify(
        {
            "data": {
                "app_name": cfg["APP_NAME"],
                "demo_mode": demo,
                "demo_seeded": bool(demo and Business.query.filter_by(is_demo=True).first()),
                "dev_mailbox": demo,
            }
        }
    )


@bp.get("/dev/outbox")
def dev_outbox():
    """Local development mailbox so verification/invite/portal links can be followed. Disabled outside demo mode."""
    cfg = current_app.config
    if not cfg["DEMO_MODE"] or cfg["APP_ENV"] == "production":
        raise NotFound()
    messages = NotificationOutbox.query.order_by(NotificationOutbox.id.desc()).limit(25).all()
    return jsonify(
        {
            "data": [
                {
                    "id": m.id,
                    "kind": m.kind,
                    "recipient": m.recipient,
                    "subject": m.subject,
                    "body": m.body,
                    "status": m.status,
                    "created_at": m.created_at.isoformat() + "Z",
                }
                for m in messages
            ]
        }
    )
