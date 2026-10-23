import os
from datetime import timedelta


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_NAME = os.environ.get("APP_NAME", "LoyalLoop")
    APP_ENV = os.environ.get("APP_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///loyalloop.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}

    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5173")
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

    SESSION_COOKIE_NAME = "ll_session"
    PORTAL_COOKIE_NAME = "ll_portal"
    SESSION_LIFETIME = timedelta(days=int(os.environ.get("SESSION_LIFETIME_DAYS", "7")))
    PORTAL_SESSION_LIFETIME = timedelta(days=30)
    COOKIE_SECURE = _bool("COOKIE_SECURE", False)

    INVITATION_TTL = timedelta(days=7)
    PASSWORD_RESET_TTL = timedelta(hours=1)
    EMAIL_VERIFY_TTL = timedelta(days=2)
    PORTAL_LINK_TTL = timedelta(hours=24)
    REDEMPTION_CODE_TTL = timedelta(days=30)

    DEMO_MODE = _bool("DEMO_MODE", False)
    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "console")
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
    EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls")  # starttls | ssl | none
    SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "15"))

    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    # Account lockout after repeated failed sign-ins (password or two-factor code).
    LOCKOUT_THRESHOLD = int(os.environ.get("LOCKOUT_THRESHOLD", "10"))
    LOCKOUT_DURATION = timedelta(minutes=int(os.environ.get("LOCKOUT_MINUTES", "15")))

    # Two-factor authentication. Fernet key for encrypting TOTP secrets; derived from SECRET_KEY if unset.
    MFA_ENCRYPTION_KEY = os.environ.get("MFA_ENCRYPTION_KEY", "")
    MFA_CHALLENGE_TTL = timedelta(minutes=5)
    MFA_CHALLENGE_MAX_ATTEMPTS = 5

    # Number of reverse proxies in front of the app (load balancer, platform router). 0 = none.
    # Needed so rate limits and logs use the real client IP instead of the proxy's.
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))

    REFERRAL_DAILY_SIGNUP_LIMIT = int(os.environ.get("REFERRAL_DAILY_SIGNUP_LIMIT", "20"))

    FRONTEND_DIST = os.environ.get(
        "FRONTEND_DIST",
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
    )


class TestConfig(Config):
    APP_ENV = "test"
    TESTING = True
    SECRET_KEY = "test-secret-key-not-for-production"
    # Set TEST_DATABASE_URL to run the suite against PostgreSQL (CI does this).
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL") or "sqlite://"
    RATELIMIT_ENABLED = False
    DEMO_MODE = True


def validate_config(config: dict) -> None:
    """Fail fast on unsafe production configuration."""
    env = config.get("APP_ENV")
    if not config.get("SECRET_KEY"):
        if env in ("development", "test"):
            config["SECRET_KEY"] = "dev-only-insecure-secret"
        else:
            raise RuntimeError("SECRET_KEY must be set outside development")
    if config.get("MFA_ENCRYPTION_KEY"):
        from cryptography.fernet import Fernet

        try:
            Fernet(config["MFA_ENCRYPTION_KEY"])
        except (ValueError, TypeError):
            raise RuntimeError("MFA_ENCRYPTION_KEY must be a Fernet key (Fernet.generate_key())")
    provider = config.get("EMAIL_PROVIDER")
    if provider not in ("console", "smtp"):
        raise RuntimeError("EMAIL_PROVIDER must be 'console' or 'smtp'")
    if provider == "smtp":
        missing = [k for k in ("SMTP_HOST", "EMAIL_FROM") if not config.get(k)]
        if missing:
            raise RuntimeError(f"EMAIL_PROVIDER=smtp requires {', '.join(missing)}")
        if config.get("SMTP_SECURITY") not in ("starttls", "ssl", "none"):
            raise RuntimeError("SMTP_SECURITY must be starttls, ssl or none")
        if env == "production" and config.get("SMTP_SECURITY") == "none":
            raise RuntimeError("SMTP_SECURITY=none is not allowed in production")
    if env == "production":
        if config.get("DEMO_MODE"):
            raise RuntimeError("DEMO_MODE cannot be enabled when APP_ENV=production")
        if not config.get("COOKIE_SECURE"):
            raise RuntimeError("COOKIE_SECURE must be true when APP_ENV=production")
        if config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            raise RuntimeError("Use PostgreSQL in production (DATABASE_URL)")
