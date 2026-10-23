"""Request IDs, access logging and optional Sentry error reporting.

Privacy rules (enforced in ``scrub_event`` and the access log):
- never send cookies, auth/CSRF/idempotency/signature headers or request bodies;
- never log query strings (they can contain one-time tokens);
- redact email addresses and long token-like strings in error messages;
- identify users by internal id only.
"""

import logging
import re
import time
import uuid

from flask import Flask, g, request

log = logging.getLogger("loyalloop.request")

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-csrf-token", "idempotency-key", "stripe-signature"}


def redact(text: str) -> str:
    return TOKEN_RE.sub("[token]", EMAIL_RE.sub("[email]", text))


def scrub_event(event: dict, hint: dict | None = None) -> dict:
    """Sentry ``before_send`` hook: drop anything that could identify customers or grant access."""
    req = event.get("request")
    if isinstance(req, dict):
        req.pop("cookies", None)
        req.pop("data", None)
        req.pop("query_string", None)
        if isinstance(req.get("headers"), dict):
            req["headers"] = {k: v for k, v in req["headers"].items() if k.lower() not in SENSITIVE_HEADERS}
        if isinstance(req.get("url"), str):
            req["url"] = req["url"].split("?", 1)[0]
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if "id" in user else {}
    for exc in (event.get("exception") or {}).get("values") or []:
        if isinstance(exc.get("value"), str):
            exc["value"] = redact(exc["value"])
    if isinstance(event.get("message"), str):
        event["message"] = redact(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict) and isinstance(logentry.get("message"), str):
        logentry["message"] = redact(logentry["message"])
    for crumb in (event.get("breadcrumbs") or {}).get("values") or []:
        if isinstance(crumb.get("message"), str):
            crumb["message"] = redact(crumb["message"])
        crumb.pop("data", None)
    return event


def init_sentry(app: Flask) -> bool:
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=app.config["APP_ENV"],
        release=app.config.get("APP_RELEASE") or None,
        send_default_pii=False,
        traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        before_send=scrub_event,
        max_request_body_size="never",
    )
    return True


def register_request_logging(app: Flask) -> None:
    @app.before_request
    def assign_request_id():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied if REQUEST_ID_RE.match(supplied) else uuid.uuid4().hex
        g.request_started = time.perf_counter()
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", g.request_id)
        except ImportError:  # pragma: no cover
            pass

    @app.after_request
    def log_request(response):
        request_id = g.get("request_id")
        if request_id:
            response.headers["X-Request-ID"] = request_id
        started = g.get("request_started")
        if started is not None and request.path.startswith("/api/"):
            duration_ms = (time.perf_counter() - started) * 1000
            user = g.get("user")
            log.info(
                "request method=%s path=%s status=%s duration_ms=%.0f request_id=%s user_id=%s",
                request.method,
                request.path,  # never the query string
                response.status_code,
                duration_ms,
                request_id,
                user.id if user else "-",
            )
        return response
