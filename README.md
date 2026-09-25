# Vehicle Compliance Management System (VCMS)

A Flask-based web application for managing and tracking vehicle compliance documents. Monitor expiry dates for PUC, Fitness, Permit, Tax, and Insurance certificates with automated status tracking, reminders, email reports, and AI-assisted document scanning.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Tests](#tests)
- [API Reference](#api-reference)
- [Production Notes](#production-notes)

---

## Features

### Dashboard
- Total vehicle count with active/expired breakdown
- Document-level statistics (valid, expiring, expired)
- Expiring today / 7-day / 30-day summary cards
- Recent activity feeds (newly added and recently updated vehicles)

### Vehicle Management
- Full CRUD operations (Create, Read, Update, Delete)
- Duplicate detection on vehicle number and chassis number
- Automatic serial number sequencing (`SN001`, `SN002`, ...)
- Bulk delete all vehicles
- Print-ready vehicle detail pages (single and batch)

### Document Compliance Tracking
Five tracked document types with color-coded status:

| Status | Color | Condition |
|--------|-------|-----------|
| Valid | Green | More than 30 days until expiry |
| Expiring Soon (30d) | Yellow | 1-30 days until expiry |
| Expiring Soon (7d) | Orange | 1-7 days until expiry |
| Expires Today | Orange | Expires on current date |
| Expired | Red | Past expiry date |
| N/A | Gray | No expiry date set |

Overall vehicle status is derived from the worst-case document status.

### Search & Filtering
- **Search**: Partial match across vehicle number, chassis number, engine number, owner name, mobile number, and policy number
- **Filter by status**: expired, valid, today, 7 days, 15 days, 30 days
- **Filter by type**: vehicle type, owner, district

### Email Reminders & Logs
- Per-vehicle expiry reminder emails with a full document status table
- Bulk reminders (all / selected / filtered vehicles), grouped by owner email
- Multi-recipient owner emails (`a@x.com, b@x.com`)
- Detailed vehicle report emails with attachments-free HTML tables
- Test email from Settings
- Every send is logged on `/reminders` (kind: `reminder` / `details` / `test`), with filters and status badges
- Optional daily auto-reminder job (APScheduler)

### AI Features
- **Document scanner** (`/ai/parse-document`): upload RC / tax receipt / permit / insurance image or PDF → OCR + AI extraction of vehicle, tax (`tax_from`, `tax_expiry`, `tax_mode`, `tax_amount`) and permit fields (`permit_from`, `permit_expiry`, `permit_auth_no`, `permit_address`); raw OCR text shown, field-comparison table against an existing vehicle (auto-fill empty fields, accept changed ones), recent scans list with view/edit, then save or update the vehicle
- **AI chat assistant** (`/ai/chat`) with saved sessions
- **AI insights** (`/ai/insights`): fleet summary and risk analysis
- Providers: OpenRouter or Google Gemini (configured in Settings or env)

### Import / Export
- **Import formats**: Excel (`.xlsx`, `.xls`), CSV (`.csv`), JSON (`.json`)
- **Column mapping**: Automatically maps common header names to internal fields
- **Validation**: Skips duplicates, reports errors with row numbers
- **Export scopes**: All vehicles, expired only, due in 7/30 days, custom date range, owner-vehicle list
- **Export formats**: Excel, CSV, JSON
- **Column selection**: Choose which fields to include in the export

### Reports
- Per-document due reports (PUC, Fitness, Tax, Permit, Insurance)
- Owner-wise vehicle grouping
- Vehicle type-wise grouping
- Monthly renewals (current month)
- Yearly renewals (current year)

### Communication
- **WhatsApp reminders**: Pre-filled messages via `wa.me` links with full vehicle compliance details
- **Click-to-call**: `tel:` links on mobile numbers

### QR Code Generation
- Generates QR codes containing structured vehicle compliance data
- Includes vehicle details, document statuses, and a report ID
- Downloadable as PNG images

### Backup & Google Drive
- One-click timestamped backups (database + settings/API keys)
- Restore from any previous backup, download backup files
- Optional Google Drive upload, list and restore with auto-sync on data changes

### UI/UX
- Dark mode interface (charcoal/dark-gray palette)
- Responsive sidebar navigation (collapsible on mobile)
- Bootstrap 5 + Font Awesome icons
- Auto-dismissing flash messages
- Back navigation button

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask 3.0.3 (application factory + blueprints) |
| Database | SQLite via Flask-SQLAlchemy 3.1.1 |
| Frontend | Bootstrap 5.3.3, Font Awesome 6.5.1 |
| Data Processing | pandas 2.2.2, openpyxl 3.1.5 |
| QR Generation | qrcode 7.4.2, Pillow 10.4.0 |
| Scheduling | APScheduler / Flask-APScheduler |
| AI | OpenRouter or Google Gemini (REST via `requests`) |
| Auth | Session-based single user (Werkzeug) |

---

## Project Structure

```
vcms/
├── run.py                 # Entry point: python run.py
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # pytest, pyflakes
├── .env.example           # Documented environment variables (copy to .env)
├── app/                   # Application package
│   ├── __init__.py        # create_app() factory: config, db, migrations,
│   │                      #   scheduler, blueprints, request hooks
│   ├── config.py          # Config class (paths derive from project root)
│   ├── extensions.py      # db = SQLAlchemy()
│   ├── middleware.py      # login_required decorator
│   ├── migrations.py      # run_migrations(), resequence_sr_nos()
│   ├── scheduler.py       # Daily auto email reminder job
│   ├── hooks.py           # Auto Google Drive sync after data-changing POSTs
│   ├── constants.py       # Shared constants (EXPORT_COLUMNS)
│   ├── models/            # SQLAlchemy models
│   │   ├── vehicle.py         # Vehicle
│   │   ├── tax.py             # TaxDetail
│   │   ├── reminder_log.py    # ReminderLog (email send log)
│   │   ├── document_scan.py   # DocumentScan (AI scans)
│   │   └── chat.py            # ChatSession / ChatMessage
│   ├── routes/            # One blueprint module per feature area
│   │   ├── auth.py            # /login, /logout
│   │   ├── dashboard.py       # /, /reports
│   │   ├── vehicles.py        # vehicle CRUD, print, QR, WhatsApp
│   │   ├── email.py           # email reminders & bulk details
│   │   ├── reminders.py       # /reminders email log
│   │   ├── data.py            # /import, /export
│   │   ├── backup.py          # /backup, Google Drive sync
│   │   ├── settings.py        # /settings, test API/email
│   │   ├── tax.py             # tax history & payments
│   │   ├── api.py             # /api/* JSON endpoints
│   │   └── ai.py              # AI chat, document parser, insights
│   ├── services/          # Business logic (no Flask routes)
│   │   ├── email_service.py   # SMTP, reminder/detail emails, logging
│   │   ├── ai_service.py      # OpenRouter/Gemini chat + document parsing
│   │   ├── google_drive.py    # OAuth, upload/restore/list
│   │   ├── vehicle_service.py # Form validation, record mapping
│   │   └── document_service.py# Scan persistence helpers
│   ├── utils/             # Cross-cutting helpers
│   │   ├── dates.py           # Date parsing/status helpers
│   │   ├── files.py           # Upload allow-list, import normalization
│   │   ├── backups.py         # create/list/restore backups
│   │   ├── whatsapp.py        # WhatsApp message builders
│   │   ├── qr.py              # QR payload builder
│   │   └── settings.py        # load/save data/settings.json
│   ├── templates/         # Jinja2 templates (moved with the package)
│   └── static/            # CSS / JS
├── scripts/
│   ├── seed_data.py       # python scripts/seed_data.py
│   └── setup_gdrive.py    # Google Drive OAuth setup helper
├── tests/                 # pytest suite (isolated temp database)
├── docs/
│   └── architecture.md    # Architecture notes
└── data/                  # Runtime data (gitignored)
    ├── vehicles.db            # SQLite database
    ├── settings.json          # UI-set settings incl. API/SMTP keys
    ├── uploads/ exports/ backups/
    ├── client_secret.json     # Google OAuth (optional)
    └── token.json             # Google OAuth token (optional)
```

URLs are unchanged from earlier versions; internal endpoint names are now
blueprint-prefixed (e.g. `vehicles.view_vehicle` instead of `view_vehicle`).

---

## Setup & Installation

### Prerequisites
- Python 3.9+ (3.10+ recommended)

### Install

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
python run.py
```

Visit **http://localhost:5000**. `data/` and the database are created
automatically on first run.

### Load Sample Data (Optional)

```bash
python scripts/seed_data.py
```

This inserts 5 demo vehicles with varied expiry statuses for testing.

### Google Drive (Optional)

```bash
# 1. Create OAuth client in Google Cloud Console (Desktop app),
#    enable the Google Drive API, download and rename to client_secret.json
# 2. Place it in data/
python scripts/setup_gdrive.py
```

---

## Configuration

Environment variables override defaults in `app/config.py`. Copy
`.env.example` to `.env` (loaded automatically) or export them in your shell:

| Variable | Purpose | Default |
|----------|---------|---------|
| `VCMS_SECRET_KEY` | Flask session secret key | `dev-secret-key-change-in-production` |
| `VCMS_DATABASE_URI` | SQLAlchemy database URI | `sqlite:///data/vehicles.db` |
| `VCMS_LOGIN_REQUIRED` | Require login for all pages | `true` |
| `VCMS_ADMIN_USER` | Admin login username | `admin` |
| `VCMS_ADMIN_PASSWORD` | Admin login password | `admin123` |
| `VCMS_CSRF_ENABLED` | Session-token CSRF checks on POST forms | `true` |
| `VCMS_AI_PROVIDER` | `openrouter` or `gemini` (Settings overrides) | `openrouter` |
| `VCMS_OPENROUTER_KEY` | OpenRouter API key | – |
| `VCMS_GOOGLE_KEY` | Google Gemini API key | – |
| `VCMS_SMTP_SERVER` / `PORT` / `USER` / `PASSWORD` / `FROM` | SMTP fallback config (Settings overrides) | – |
| `VCMS_EMAIL_REMINDER_HOUR` | Hour (0-23) for the daily auto reminder | `9` |
| `VCMS_GDRIVE_ENABLED` | Master switch for Google Drive sync | `false` |

Secrets (API keys, SMTP password) can also be set from the **Settings** page;
they are stored in `data/settings.json` (git-ignored).

---

## Usage

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Overview of all vehicle compliance stats |
| Vehicle List | `/vehicles` | Search, filter, and manage all vehicles |
| Add Vehicle | `/vehicles/add` | Add a new vehicle record |
| Email Logs | `/reminders` | All sent emails with kind/status filters |
| Import | `/import` | Bulk import from Excel/CSV/JSON |
| Export | `/export` | Configure and download vehicle data |
| Reports | `/reports` | Generate compliance reports |
| Backup | `/backup` | Create, restore, or download backups |
| Settings | `/settings` | API keys, SMTP, auto-reminder toggles |
| AI Chat | `/ai/chat` | Fleet compliance assistant |
| AI Scanner | `/ai/parse-document` | Extract vehicle data from document photos |
| AI Insights | `/ai/insights` | Fleet risk analysis |
| Vehicle Tax | `/vehicles/<id>/tax` | View tax payment history |

### Default Login

- **Username**: `admin`
- **Password**: `admin123`

Change these via `VCMS_ADMIN_USER` / `VCMS_ADMIN_PASSWORD` before exposing the app.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs against a throwaway temp database (your `data/vehicles.db` is
never touched), covers page rendering (catches broken endpoint names), vehicle
CRUD/validation, email logging, and AI tax/permit extraction.

Lint:

```bash
pyflakes app run.py tests scripts
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/vehicle/<id>` | GET | Returns vehicle data as JSON |
| `/api/check-duplicate?field=<col>&value=<v>` | GET | Duplicate check as JSON |

---

## Production Notes

This application uses simple session-based single-user authentication. For production or multi-user deployments, consider:

- **Flask-Login** with hashed passwords stored in the database
- **Session-token CSRF protection** is built in on all POST forms (disable with `VCMS_CSRF_ENABLED=false`); switch to Flask-WTF if you add more complex form handling
- **PostgreSQL** or **MySQL** instead of SQLite for concurrent access
- **Gunicorn** or **uWSGI** as a production WSGI server
- **Nginx** as a reverse proxy with HTTPS
- Move `SECRET_KEY` and credentials to a `.env` file or secrets manager
- Add rate limiting and input sanitization for public-facing deployments
