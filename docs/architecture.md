# VCMS Architecture

## Overview

VCMS is a single-process Flask application built with an application factory
and feature blueprints. There is no external queue or async worker: SMTP and
AI calls are made in-request, and background work (daily reminder job, Drive
auto-sync) runs in-process.

## Application lifecycle

```
run.py  ──►  app.create_app()
                 │
                 ├─ load .env (optional, python-dotenv)
                 ├─ app.config.from_object(Config)
                 ├─ db.init_app(app)                  # app/extensions.py
                 ├─ ensure data/ folders exist
                 ├─ with app.app_context():
                 │     db.create_all()                # create tables
                 │     run_migrations()               # additive column migrations
                 │     resequence_sr_nos()            # keep SN001..SN00N contiguous
                 │     start_scheduler(app)           # daily email job (APScheduler)
                 ├─ register_blueprints(app)          # app/routes/__init__.py
                 └─ register_hooks(app)               # app/hooks.py (Drive auto-sync)
```

`create_app()` takes no arguments; test code overrides behaviour through
environment variables (`VCMS_DATABASE_URI`) and by patching module attributes
(see `tests/conftest.py`).

## Request flow

```
browser ──► blueprint route (app/routes/*.py)
                │  @login_required (app/middleware.py → auth.login)
                │
                ├─ service call (app/services/*)   business logic, SMTP, AI, Drive
                ├─ model query (app/models/*)      SQLAlchemy
                └─ render app/templates/*.html  or  redirect(url_for(...))
                       │
                       ▼
             after_request hook (app/hooks.py)
                POST + endpoint in GDRIVE_SYNC_ENDPOINTS
                └─► background thread: backup → Drive upload
```

## Blueprints

| Blueprint | Prefix-free routes | Covers |
|-----------|--------------------|--------|
| `auth` | `/login`, `/logout` | Session auth |
| `main` | `/`, `/reports` | Dashboard, reports |
| `vehicles` | `/vehicles…` | CRUD, print, QR, WhatsApp |
| `email` | `/vehicles/…/email-*` | Reminder & details emails |
| `reminders` | `/reminders` | Email send log UI |
| `data` | `/import`, `/export` | Excel/CSV import & export |
| `backup` | `/backup`, `/settings/google/*` | Backups, Drive sync |
| `settings` | `/settings`, `/settings/test-*` | Config UI, connectivity tests |
| `tax` | `/vehicles/<id>/tax…` | Tax payment history |
| `api` | `/api/*` | JSON endpoints |
| `ai` | `/ai/*` | Chat, document scanner, insights |

URL paths are unchanged from the pre-blueprint layout; only internal endpoint
names gained the prefix (e.g. `vehicles.view_vehicle`). Templates must always
use `url_for("<blueprint>.<name>")`.

## Layers and dependencies

- **routes** depend on services, models, utils — never the other way around.
- **services** (`email_service`, `ai_service`, `google_drive`,
  `vehicle_service`, `document_service`) hold business logic and third-party
  integrations. They depend on models/utils only.
- **models** are plain SQLAlchemy classes; `app/models/__init__.py` re-exports
  `db` and all models so routes can use `from app.models import db, Vehicle`.
- **utils** are stateless helpers (dates, files, backups, WhatsApp text, QR
  payload, settings IO). `app/utils/__init__.py` re-exports them.
- **extensions.py** owns the single `db` object, avoiding circular imports
  between `models` and the app factory.

## Data and paths

All paths derive from `app/config.py`:

- `BASE_DIR` — project root (parent of `app/`)
- `DATA_DIR` — `<root>/data` (git-ignored)
- SQLite DB — `data/vehicles.db` (override: `VCMS_DATABASE_URI`)
- Settings — `data/settings.json` (UI-managed secrets; loaded by
  `app/utils/settings.py`, env vars act as fallback)
- `uploads/`, `exports/`, `backups/` — under `data/`
- Google Drive `client_secret.json` / `token.json` — under `data/`

## Persistence changes

`app/migrations.py::run_migrations()` applies additive schema changes on every
startup (idempotent), e.g. `reminder_logs.kind` (+ backfill of legacy `NULL`
rows to `'reminder'`, table rebuild to make `vehicle_id` nullable) and permit /
tax columns on `vehicles`. `resequence_sr_nos()` renumbers `SN001…` after
deletes so serial numbers stay contiguous.

## Background work

- **Scheduler** (`app/scheduler.py`): APScheduler cron job at
  `VCMS_EMAIL_REMINDER_HOUR` sends daily expiry reminders when
  `auto_reminders_enabled` is on. Skipped in debug reloader child.
- **Hooks** (`app/hooks.py`): after successful POSTs to data-mutating endpoints,
  a daemon thread creates a local backup and uploads it to Drive (only when
  `gdrive_auto_sync` is on and an OAuth token exists).

## Email subsystem

`app/services/email_service.py`:

- Builds reminder / consolidated / details HTML bodies (inline styles, table layout).
- `send_email()` → `send_email_via_smtp()`; configuration comes from
  `data/settings.json` with `VCMS_SMTP_*` env fallbacks.
- Every send is recorded in `reminder_logs` (`kind`: `reminder` | `details` |
  `test`, `vehicle_id` nullable for grouped/test rows) via `log_email()` /
  `log_email_result()`; warnings are stored on the row without failing it.

## AI subsystem

`app/services/ai_service.py`:

- `chat_completion()` — OpenRouter or Gemini REST call with retry/backoff on
  transient 429/503.
- `PARSE_PROMPT` + `parse_document_text()` — structured-JSON extraction of
  vehicle, tax and permit fields from OCR text; used by `/ai/parse-document`.
- API keys come from `data/settings.json` with `VCMS_OPENROUTER_KEY` /
  `VCMS_GOOGLE_KEY` env fallbacks.

## Testing

`tests/conftest.py` runs every test against a fresh temp SQLite database:

1. set `VCMS_DATABASE_URI` before importing the app,
2. disable the scheduler (`app.scheduler.start_scheduler` patched),
3. point `app.utils.settings.SETTINGS_FILE` at a temp file so real secrets are
   never read or written,
4. build the app once per session; each test gets a logged-in test client.

Suites: page-render sweep (catches broken `url_for` names), vehicle CRUD and
validation, email logging/grouping/filters, AI tax+permit extraction.
