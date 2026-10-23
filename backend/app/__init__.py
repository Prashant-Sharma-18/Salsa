import logging
import os

import click
from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from .config import Config, validate_config
from .errors import error_body, register_error_handlers
from .extensions import db, limiter, migrate

API_PREFIX = "/api/v1"


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()


def create_app(config_object=Config, overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_object)
    if overrides:
        app.config.update(overrides)
    validate_config(app.config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if app.config["APP_ENV"] == "production" and app.config["EMAIL_PROVIDER"] == "console":
        logging.getLogger("loyalloop").warning("EMAIL_PROVIDER=console in production: no emails will be delivered")

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    limiter.init_app(app)
    if app.config["CORS_ORIGINS"]:
        CORS(
            app,
            resources={rf"{API_PREFIX}/*": {"origins": app.config["CORS_ORIGINS"]}},
            supports_credentials=True,
            allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        )

    register_error_handlers(app)

    @app.errorhandler(IntegrityError)
    def handle_integrity(err):
        db.session.rollback()
        return jsonify(
            error_body("conflict", "This change conflicts with existing data (possibly a duplicate request).")
        ), 409

    from .api import analytics, auth, business, customers, portal, rewards, system

    for module in (auth, business, customers, rewards, analytics, portal, system):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX + (module.bp.url_prefix or ""))

    @app.before_request
    def reset_request_cache():
        for key in ("user_session", "tenant", "user", "customer", "portal_session"):
            g.pop(key, None)

    @app.before_request
    def require_json_for_writes():
        # Cross-site HTML forms cannot send application/json, which closes the classic CSRF vector
        # for endpoints that run before a session (sign in, join). Authenticated writes also need X-CSRF-Token.
        if (
            request.path.startswith(API_PREFIX)
            and request.method in ("POST", "PUT", "PATCH", "DELETE")
            and request.content_length
            and not request.is_json
        ):
            return jsonify(error_body("unsupported_media_type", "Send JSON with Content-Type: application/json")), 415

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.path.startswith(API_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        if app.config["APP_ENV"] == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    _register_spa(app)
    _register_cli(app)
    return app


def _register_spa(app: Flask):
    """Serve the built frontend (frontend/dist) in production-style single-origin deployments."""
    dist = os.path.abspath(app.config["FRONTEND_DIST"])

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            return jsonify(error_body("not_found", "Not found")), 404
        if not os.path.isdir(dist):
            return jsonify({"message": "API server. Run the frontend with `npm run dev` in /frontend."}), 200
        if path and os.path.isfile(os.path.join(dist, path)):
            return send_from_directory(dist, path)
        return send_from_directory(dist, "index.html")


def _register_cli(app: Flask):
    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True, help="Delete existing demo business data first")
    def seed_demo(reset):
        """Seed clearly labelled demo data (refuses to run in production)."""
        from .seed import seed

        seed(reset=reset)

    @app.cli.command("expire-points")
    def expire_points():
        """Apply points expiry and expire stale redemption codes for every business."""
        from .models import Business
        from .services import ledger, redemptions

        for business in Business.query.all():
            balances = ledger.process_expirations(business.id)
            codes = redemptions.expire_stale(business.id)
            db.session.commit()
            click.echo(f"{business.slug}: expired {balances} balances, {codes} codes")

    @app.cli.command("reconcile")
    def reconcile():
        """Compare cached balances with ledger sums. Exit code 1 if any mismatch."""
        from .models import Business
        from .services import ledger

        bad = 0
        for business in Business.query.all():
            for row in ledger.reconcile(business.id):
                bad += 1
                click.echo(f"MISMATCH business={business.slug} {row}")
        click.echo("All balances reconcile with the ledger." if not bad else f"{bad} mismatches found")
        if bad:
            raise SystemExit(1)

    @app.cli.command("email-worker")
    @click.option("--interval", default=10, show_default=True, help="Seconds between outbox polls")
    def email_worker(interval):
        """Continuously deliver queued emails (run as a separate process in production)."""
        import time

        from .email import deliver_pending

        click.echo(f"Email worker started (provider={app.config['EMAIL_PROVIDER']}, interval={interval}s)")
        while True:
            try:
                sent = deliver_pending()
                if sent:
                    click.echo(f"Sent {sent} messages")
            except Exception:  # keep the worker alive; errors are logged
                logging.getLogger("loyalloop.email").exception("Email worker iteration failed")
                db.session.rollback()
            finally:
                db.session.remove()
            time.sleep(interval)

    @app.cli.command("deliver-emails")
    def deliver_emails():
        """Send pending outbox messages through the configured provider."""
        from .email import deliver_pending

        click.echo(f"Sent {deliver_pending()} messages")
