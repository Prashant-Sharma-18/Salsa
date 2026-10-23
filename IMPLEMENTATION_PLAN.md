# LoyalLoop — Implementation Plan

## Detected stack
The repository was empty except for the build brief, so the brief's default stack is used:

| Layer | Choice |
|---|---|
| Backend | Python 3.12, Flask 3 (app factory + Blueprints), SQLAlchemy 2, Flask-Migrate/Alembic |
| Database | PostgreSQL (production), SQLite (local dev / tests) |
| Auth | Server-side session table + opaque HttpOnly SameSite cookie, header-based CSRF token, Argon2id password hashing |
| Rate limiting | Flask-Limiter (memory in dev, Redis URI configurable) |
| Frontend | React 18 + TypeScript + Vite, React Router 6, TanStack Query 5, React Hook Form + Zod, SCSS partials with design tokens, lucide-react icons |
| Tests | Pytest (backend), Vitest + React Testing Library (frontend) |
| Deploy | Dockerfile (multi-stage) + docker-compose with PostgreSQL |

## Architecture
Modular monolith:

```
backend/app/
  models.py        SQLAlchemy models (tenant-scoped)
  security.py      sessions, CSRF, password/token hashing, permission matrix, decorators
  validation.py    input validation/normalisation helpers
  services/        business logic (ledger, purchases, redemptions, referrals, analytics, ...)
  api/             thin Blueprint route handlers under /api/v1
  email.py         provider interface + console/outbox adapter
  seed.py          demo data (guarded against production)
frontend/src/
  api/             fetch client (CSRF, error handling)
  components/      reusable UI primitives
  pages/           one module per screen
  styles/          SCSS tokens + partials
```

## Task checklist

### Phase 1 — scaffold
- [x] Inspect repository (empty)
- [x] Backend venv, Flask app factory, config, extensions
- [x] Frontend Vite + TS scaffold
- [x] `.env.example`, README, migrations

### Phase 2 — database and auth
- [x] Models + Alembic migration
- [x] Sign up / sign in / sign out / password reset / email verification
- [x] Business membership + tenant context derived from session
- [x] Demo seed with production guard

### Phase 3 — loyalty core
- [x] Program settings (earning, minimum spend, redemption, referrals, expiry)
- [x] Customer enrollment, dedupe, search, pagination, consent records
- [x] Append-only ledger with cached balance + reconciliation
- [x] Purchase awards (idempotency key + unique receipt reference, transaction)
- [x] Rewards CRUD, atomic redemption with unique codes, status transitions
- [x] Manager adjustments and reversals with mandatory reason

### Phase 4 — referrals and staff
- [x] Referral codes/links, attribution, qualification on first eligible purchase
- [x] Self-referral and duplicate reward prevention, rate limits
- [x] Locations, location access, invitations (expiring, single use), roles
- [x] Audit log

### Phase 5 — dashboard and portal
- [x] Analytics from DB queries with metric definitions
- [x] CSV exports with permission + audit
- [x] Customer portal via expiring single-use access links
- [x] Public join page with referral attribution

### Phase 6 — polish and verification
- [x] Responsive SCSS, focus states, reduced motion
- [x] Tenant isolation, auth, ledger, referral tests
- [x] Run tests, lint, build; record results in README
- [x] Browser E2E (Playwright) and HTTP E2E smoke script
- [x] PostgreSQL 16 verification (tests, migrations up/down, seed, E2E)
- [x] GitHub Actions CI (backend on SQLite + PostgreSQL, frontend, E2E, Docker compose smoke)
- [ ] Docker run verified locally — no Docker on the build machine; covered by the CI `docker` job

### Security hardening
- [x] TOTP two-factor sign-in with recovery codes, replay protection, encrypted secrets
- [x] Per-business "require two-factor for owners and managers" policy
- [x] Account lockout with email notification
- [x] Trusted-proxy client IP handling (`TRUSTED_PROXY_COUNT`)
- [x] Dependency vulnerability scan in CI + Dependabot; all known vulnerabilities fixed

### Commercial
- [x] Plans, trial, server-side limits, read-only mode for lapsed accounts
- [x] Billing provider boundary: simulated (dev) and Stripe (Checkout, Portal, signed webhooks)
- [ ] Live Stripe verification — needs a Stripe account (test mode)
- [x] Platform admin console: overview, business search, suspend/reinstate, manual plan and trial changes (audited, no customer data)

### P1 (implemented only where cheap and safe)
- [x] Points expiry processing (CLI + owner action)
- [x] Email provider adapter (console/outbox)
- [x] Branded customer page (brand color, logo, rules)
- [x] QR codes: printable counter sign (join page) and customer referral QR
- [ ] Webhooks — deferred
- [x] SMTP email provider + background worker (works with SendGrid, Postmark, SES, Mailgun)
