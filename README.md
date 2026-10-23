# LoyalLoop

LoyalLoop is a multi-tenant loyalty and referral MVP for independent US retailers, salons, gyms, cafés and small chains. Merchants use it to run a points program, issue and redeem rewards, track referrals, manage staff across locations, and review analytics. Customers get a mobile-friendly rewards page, reached through a secure emailed link.

> The name is a working title and is configurable through `APP_NAME`. Trademark availability has not been checked.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3 (app factory + Blueprints), SQLAlchemy 2, Flask-Migrate/Alembic, Argon2, Flask-Limiter |
| Database | PostgreSQL in production. SQLite for local development and tests. |
| Frontend | React 18, TypeScript, Vite 5, React Router 6, TanStack Query 5, React Hook Form + Zod, SCSS design tokens, lucide-react icons |
| Tests | Pytest (backend), Vitest + React Testing Library (frontend), Playwright and a Python HTTP smoke script (end-to-end) |

```
backend/   Flask API (app/api = routes, app/services = business logic, app/models.py, migrations/, tests/)
frontend/  React app (src/pages, src/components, src/styles, e2e/)
docs/      API reference, privacy notice template
```

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [SECURITY.md](SECURITY.md) and [docs/API.md](docs/API.md).

## Local setup

Prerequisites: Python 3.12, Node 20.

```bash
cp .env.example .env            # placeholders; DEMO_MODE=true for local use

# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows (Git Bash: source .venv/Scripts/activate); macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
flask db upgrade                # creates backend/instance/loyalloop.db
flask seed-demo                 # optional, clearly labelled sample data
flask run --port 5000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :5000)
```

### Demo mode (local only)

`flask seed-demo` creates **Maple Street Coffee (Demo)**. It has two locations, 14 customers, four rewards, 90 days of ledger history, redemptions in several states and referrals. The sign-in page has one-click **Demo owner / manager / staff** buttons. You can also sign in with these accounts:

| Role | Email | Password |
|---|---|---|
| Owner | owner@demo.loyalloop.test | `DemoPass-2024!` |
| Manager | manager@demo.loyalloop.test | `DemoPass-2024!` |
| Staff (Downtown only) | staff@demo.loyalloop.test | `DemoPass-2024!` |

- Demo data carries visible labels in the UI.
- Run `flask seed-demo --reset` to rebuild it. This deletes only demo records.
- Seeding, demo login and demo accounts are all refused when `APP_ENV=production` or `DEMO_MODE` is off.

**Dev mailbox:** emails go to an outbox table instead of being sent. In demo mode, open <http://localhost:5173/dev/mailbox> to follow verification, invitation, password-reset and customer sign-in links.

### Trying the customer side

1. From a customer's page, click **Email loyalty page link**, then open the link from the dev mailbox.
2. The public join page is at `/join/<business-slug>`. Referral links look like `/join/<slug>?ref=CODE`.
3. To request a sign-in link, use `/portal/<business-slug>`.

## Commands

| Purpose | Command (from `backend/`) |
|---|---|
| Apply migrations | `flask db upgrade` |
| Create migration after model change | `flask db migrate -m "message"` and review the generated file |
| Check models match migrations | `flask db check` |
| Seed / reset demo data | `flask seed-demo [--reset]` |
| Expire inactive balances and stale codes | `flask expire-points` (schedule daily via cron) |
| Verify cached balances against the ledger | `flask reconcile` (exit 1 on mismatch) |
| Send queued emails via the provider | `flask deliver-emails` |
| Backend tests | `python -m pytest -q` |
| Lint | `ruff check .` |

| Purpose | Command (from `frontend/`) |
|---|---|
| Dev server | `npm run dev` |
| Unit/component tests | `npm test` |
| Type check | `npm run typecheck` |
| Production build | `npm run build` |
| Browser E2E (needs server, see below) | `npm run e2e` |

### End-to-end tests

The E2E tests run against Flask serving the built frontend, with the demo seeded:

```bash
cd frontend && npm run build
cd ../backend && flask seed-demo --reset && DEMO_MODE=true flask run --port 5000
# another terminal:
python backend/scripts/smoke_e2e.py http://127.0.0.1:5000     # HTTP journey: MVP criteria 1–8 + portal
cd frontend && npm run e2e                                     # Playwright, uses installed Chrome (E2E_BROWSER_CHANNEL=msedge for Edge)
```

## Verification results

All results below come from runs on 2026-10-23 on Windows 10 with Python 3.12.7 and Node 20.19.6.

| Check | Command | Result |
|---|---|---|
| Backend tests | `python -m pytest -q` | **46 passed** |
| Backend lint | `ruff check .` | All checks passed |
| Migrations vs models | `flask db check` | No new upgrade operations detected |
| Fresh DB | `flask db upgrade` + `seed-demo` + `seed-demo --reset` + `reconcile` | Applied cleanly. All balances reconcile. |
| Production guards | `create_app()` with `APP_ENV=production` | Refuses to start with demo mode on, with SQLite, or without `SECRET_KEY` |
| Frontend tests | `npm test` | **23 passed** |
| Type check | `npm run typecheck` | No errors |
| Build | `npm run build` | Built (420 kB JS / 122 kB gzip) |
| HTTP E2E | `scripts/smoke_e2e.py` | Passed. Covers signup, verify, onboarding, program config, location, staff invite (reuse rejected), enrollment with referral, purchases (duplicate not double-counted, wrong-location 403), redemption issue/validate/complete, referral reward, ledger, analytics, CSV export (staff 403), audit, portal magic link (reuse rejected), public join, SPA served. |
| Browser E2E | `npm run e2e` (Chrome) | **4 passed**: owner visits all 11 main pages with no console or runtime errors, staff purchase → redemption → validation journey, enrollment with validation feedback, no horizontal overflow at 375 px |

**Not tested:** PostgreSQL (no Postgres or Docker available on the build machine), the Docker image, and docker-compose. These files are provided but have not been run.

Backend test coverage includes:
- Unauthenticated access is denied.
- Cross-tenant access is denied for customers, ledger, rewards, redemptions, referrals, exports, analytics and locations.
- Staff and manager privilege limits are enforced.
- Deactivation and role changes take effect immediately.
- Location restrictions are enforced.
- Invitations expire and are single-use.
- Password reset is single-use and revokes sessions.
- CSRF and JSON enforcement work.
- Points are calculated correctly, including minimum spend and eligible amounts.
- Idempotency keys and duplicate receipts do not double-award.
- Redemption succeeds with enough points and fails without them, and status transitions are enforced.
- Expired codes are refunded.
- Stock limits are enforced.
- Concurrent redemptions (6 threads, balance covers 2) cannot overdraw.
- Reversals create new entries and cannot overdraw.
- Adjustments need a reason and permission.
- Ledger rows are append-only.
- Reconciliation and inactivity expiry work, and expiry is idempotent.
- Referral qualification and rewards work, rewards pay only once, self-referral is rejected, and clients cannot bypass qualification.
- Portal links are single-use and expire.
- Portal data is scoped to one customer.
- Portal redemption and consent history work.
- Join does not reveal whether an email exists.
- Anonymization removes personal details and keeps the ledger.

## How points work

- **Earning:** `floor(eligible_cents × points_per_dollar / 100)`, using integer maths only. Purchases below the program's minimum spend earn nothing.
- **Money:** stored as integer cents and parsed with `Decimal`. Floating-point arithmetic is never used for currency.
- **Balance:** `customers.points_balance` is a cached balance. It changes in the same transaction as each ledger insert, through a guarded atomic `UPDATE … WHERE points_balance + delta >= 0`. Each ledger row stores `balance_after`. `flask reconcile` checks that the cache equals `SUM(points)` for every customer.
- **Corrections:** ledger rows are never edited or deleted. Reversals and manual adjustments are new rows, each with an actor and a reason, and they are audited.
- **Expiry policy (optional):** a whole balance expires after N days with no earning or redemption activity. The expiry runs from `flask expire-points` or the owner's **Run expiry now** button. It is idempotent.
- **Redemptions:** points are debited when a code is issued. A code moves from `issued` to `redeemed`, `cancelled` or `expired`. Cancelled and expired codes refund points. The app does **not** connect to a POS or payment terminal. Staff apply the reward at their register.
- **Referrals:** a referral moves from `created` (staff-recorded invite) to `signed_up`, `qualified` and `rewarded`, or to `rejected`. A referral qualifies on the friend's first staff-recorded purchase at or above the configured minimum.

## Deployment

The `Dockerfile` builds the frontend, then runs Flask and gunicorn. That one container serves both `/api/v1` and the SPA from a single origin, which keeps cookies same-site and lets CORS stay off. `docker-compose.yml` starts the app with PostgreSQL for local trials. Neither file has been executed (see above).

A typical production setup:
1. A managed PostgreSQL instance with daily automated backups and point-in-time recovery. Test restores regularly.
2. The container on any platform that can run it (Render, Fly.io, ECS, Cloud Run), with HTTPS terminated at the platform.
3. Environment variables: `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `COOKIE_SECURE=true`, `PUBLIC_BASE_URL`, `RATELIMIT_STORAGE_URI=redis://…`.
4. Migrations run on start (`flask db upgrade`). For zero-downtime deploys, run them as a separate release step.
5. Scheduled jobs: `flask expire-points` daily, `flask reconcile` daily with alerting, `flask deliver-emails` every minute once a real provider exists.

## External services still required

| Need | Status |
|---|---|
| Email delivery | Only a `console` adapter exists. To add a provider, implement `send()` in `backend/app/email.py` and select it with `EMAIL_PROVIDER`. |
| Redis (production rate limiting) | Optional locally. Recommended in production. |
| Billing | Not implemented. `businesses.plan` marks where Stripe would connect. |
| POS / payment terminal | Out of scope. Purchases are entered manually. |

## Known limitations

- PostgreSQL, Docker and docker-compose have not been tested.
- No production email provider.
- No staff MFA.
- No CI pipeline.
- Analytics daily series are grouped in Python, which is fine at MVP scale. Move this into SQL for large tenants.
- Link-click referral tracking (`clicked` state) is not recorded. This is deliberate, to avoid collecting unnecessary data.
- The P1 items not built are QR codes, webhooks, promotion campaigns and scheduled-job infrastructure.
- The UI was designed against WCAG 2.2 AA (labels, focus states, contrast tokens, reduced motion, keyboard-operable dialogs). It has not had an accessibility audit and does not claim compliance.
- See [SECURITY.md](SECURITY.md) for security limitations.
