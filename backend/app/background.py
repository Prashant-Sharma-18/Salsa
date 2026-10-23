"""In-process background tasks for single-service hosting (e.g. Render free tier).

When ``RUN_BACKGROUND_IN_WEB`` is true, each web process starts one daemon
thread on its first request that:
- delivers queued email every ``BACKGROUND_EMAIL_INTERVAL`` seconds;
- runs maintenance (points expiry, stale redemption codes, birthday bonuses)
  every ``BACKGROUND_MAINTENANCE_INTERVAL`` seconds.

Every task here is already safe to run concurrently and repeatedly (atomic
email claims, idempotency keys), so several processes may run it at once.
On hosts that sleep idle services, tasks pause until the next request wakes
the service: a birthday that falls entirely within a sleeping period is
missed. Use the separate worker and cron job (render.yaml) for production.
"""

import logging
import threading
import time

from flask import Flask

log = logging.getLogger("loyalloop.background")

_started = False
_lock = threading.Lock()


def run_maintenance() -> dict:
    """One maintenance pass over all businesses (call inside an app context)."""
    from .extensions import db
    from .models import Business
    from .services import ledger, promotions, redemptions

    totals = {"expired_balances": 0, "expired_codes": 0, "birthday_bonuses": 0}
    for business in Business.query.all():
        try:
            totals["expired_balances"] += ledger.process_expirations(business.id)
            totals["expired_codes"] += redemptions.expire_stale(business.id)
            totals["birthday_bonuses"] += promotions.award_birthday_bonuses(business)
            db.session.commit()
        except Exception:  # one business failing must not stop the others
            db.session.rollback()
            log.exception("maintenance failed business_id=%s", business.id)
    return totals


def tick(app: Flask, now: float, state: dict) -> None:
    """Run whatever is due. ``state`` holds the last run times (per thread)."""
    from .email import deliver_pending
    from .extensions import db

    with app.app_context():
        try:
            if now - state.get("email", 0) >= app.config["BACKGROUND_EMAIL_INTERVAL"]:
                state["email"] = now
                sent = deliver_pending()
                if sent:
                    log.info("background email sent=%s", sent)
            if now - state.get("maintenance", 0) >= app.config["BACKGROUND_MAINTENANCE_INTERVAL"]:
                state["maintenance"] = now
                totals = run_maintenance()
                if any(totals.values()):
                    log.info("background maintenance %s", totals)
        except Exception:
            db.session.rollback()
            log.exception("background tick failed")
        finally:
            db.session.remove()


def _loop(app: Flask) -> None:
    state: dict = {}
    # Small initial delay so the first request is not competing with maintenance.
    time.sleep(2)
    while True:
        tick(app, time.monotonic(), state)
        time.sleep(1)


def ensure_started(app: Flask) -> bool:
    """Start the background thread once per process. Returns True if started by this call."""
    global _started
    if _started or not app.config.get("RUN_BACKGROUND_IN_WEB") or app.config.get("TESTING"):
        return False
    with _lock:
        if _started:
            return False
        thread = threading.Thread(target=_loop, args=(app,), name="loyalloop-background", daemon=True)
        thread.start()
        _started = True
    log.info("background tasks started in web process")
    return True
