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

    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    REFERRAL_DAILY_SIGNUP_LIMIT = int(os.environ.get("REFERRAL_DAILY_SIGNUP_LIMIT", "20"))

    FRONTEND_DIST = os.environ.get(
        "FRONTEND_DIST",
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
    )


class TestConfig(Config):
    APP_ENV = "test"
    TESTING = True
    SECRET_KEY = "test-secret-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
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
    if env == "production":
        if config.get("DEMO_MODE"):
            raise RuntimeError("DEMO_MODE cannot be enabled when APP_ENV=production")
        if not config.get("COOKIE_SECURE"):
            raise RuntimeError("COOKIE_SECURE must be true when APP_ENV=production")
        if config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            raise RuntimeError("Use PostgreSQL in production (DATABASE_URL)")
