# Vehicle Compliance Management System (VCMS)

A Flask-based web application for managing and tracking vehicle compliance documents. Monitor expiry dates for **PUC, Fitness, Permit, Tax, and Insurance** certificates with automated status tracking, reminders (Email/WhatsApp), reporting, and AI-powered document scanning.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Routes Reference](#routes-reference)
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
- Duplicate detection on vehicle number, chassis number, engine number, owner name, mobile, and policy number
- Automatic serial number sequencing (`SN001`, `SN002`, ...) with re-sequencing on delete
- Bulk delete all vehicles and print-ready detail pages (single, batch, and QR batches)

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
- **Filter by status**: expired, valid, today, 2/7/15/30 days
- **Filter by type**: vehicle type, owner, district

### Import / Export
- **Import formats**: Excel (`.xlsx`, `.xls`), CSV (`.csv`), JSON (`.json`)
- **Column mapping**: Automatically maps common header names to internal fields (PUC, fitness, NP auth no, etc.)
- **Validation**: Skips duplicates or updates them, reports errors with row numbers
- **Export scopes**: All vehicles, expired only, owner-vehicle list, due in 7/30 days, custom date range
- **Export formats**: Excel, CSV, JSON with selectable columns

### Reports
- Per-document due reports (PUC, Fitness, Tax, Permit, Insurance)
- Owner-wise and vehicle type-wise grouping
- Monthly and yearly renewal reports

### Communication & Reminders
- **WhatsApp reminders**: Pre-filled `wa.me` messages with full compliance details or expired/expiring-only alerts
- **Click-to-call**: `tel:` links on mobile numbers
- **Email reminders**: Per-vehicle, bulk, selected-vehicle, and full-detail reports via SMTP or Mailgun
- **Reminder logs**: Track all sent/failed reminders with filter and clear options
- **Auto-reminders**: Daily scheduled job (APScheduler cron) for documents expiring in 3 or 0 days

### QR Code Generation
- Generates QR codes containing structured offline vehicle compliance data (including a report ID)
- Downloadable as PNG images and printable in batches of 6 per page

### Backup & Restore
- One-click timestamped SQLite backups organized by date, with duplicate detection
- Restore from local backup or uploaded `.db` file
- **Google Drive sync**: OAuth-based connect, auto-sync after writes, cloud backup/restore

### AI Features
- **AI Chat Assistant**: Ask natural-language questions about your fleet (case-insensitive vehicle/owner matching); multi-turn session history
- **AI Document Parser**: OCR (Tesseract + PyMuPDF for PDFs) then AI extraction of vehicle details from scanned RC/Insurance/PUC/Fitness documents; field-by-field comparison with existing records; auto-fill or review-then-apply
- **AI Insights**: Fleet-wide compliance risk analysis, top issues, at-risk vehicles, and monthly outlook
- **Provider support**: OpenRouter or Google Gemini (configurable in Settings)

### UI/UX
- Dark mode interface (charcoal/dark-gray palette)
- Responsive sidebar navigation (collapsible on mobile)
- Bootstrap 5 + Font Awesome icons
- Auto-dismissing flash messages
- Back navigation button and prev/next navigation between filtered vehicles

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask 3.0.3 |
| Database | SQLite via Flask-SQLAlchemy 3.1.1 |
| Frontend | Bootstrap 5.3.3, Font Awesome 6.5.1 |
| Data Processing | pandas 2.2.2, openpyxl 3.1.5 |
| QR Generation | qrcode 7.4.2, Pillow 10.4.0 |
| OCR | pytesseract 0.3.10, PyMuPDF 1.24+ |
| Scheduling | APScheduler (daily email reminders) |
| AI | requests-based calls to OpenRouter / Google Gemini |
| Email | SMTP (`smtplib`) or Mailgun REST API |
| Google Drive | google-api-python-client, google-auth-oauthlib |
| Auth | Werkzeug 3.0.3 (password hashing) |

---

## Project Structure

```
vcms/
├── app.py              # Flask app factory, routes, auth, scheduler
├── models.py           # SQLAlchemy models (Vehicle, TaxDetail, Chat*, ReminderLog, ScanHistory)
├── config.py           # Configuration class (env-driven)
├── utils.py            # Date parsing, import/export, backups, WhatsApp, QR, settings
├── ai_service.py       # AI chat / document parsing / insights (OpenRouter + Gemini)
├── email_service.py    # SMTP / Mailgun reminders + reminder logging
├── google_drive.py     # Google Drive backup sync (OAuth)
├── seed_data.py        # Sample data loader for demo/testing
├── requirements.txt    # Python dependencies
├── vehicles.db         # SQLite database (auto-created)
├── settings.json       # Runtime settings (AI keys, SMTP, GDrive) — created on first save
├── templates/          # Jinja2 HTML templates (23 files)
│   ├── layout.html             # Base layout with sidebar navigation
│   ├── login.html              # Login page
│   ├── dashboard.html          # Main dashboard
│   ├── vehicle_list.html       # Vehicle list with search/filter
│   ├── add_vehicle.html        # Add vehicle form
│   ├── edit_vehicle.html       # Edit vehicle form
│   ├── view_vehicle.html       # Vehicle detail view
│   ├── print_vehicle.html      # Single vehicle print view
│   ├── print_vehicles.html     # Batch print view
│   ├── print_qr.html           # Batch QR print view
│   ├── vehicle_qr_dates.html   # QR detail view
│   ├── import_excel.html       # Import page
│   ├── export_excel.html       # Export configuration page
│   ├── reports.html            # Reports page
│   ├── reminders.html          # Email reminder logs
│   ├── backup.html             # Backup management (+ GDrive)
│   ├── settings.html           # Settings page (AI, Email, GDrive)
│   ├── ai_chat.html            # AI chat assistant
│   ├── ai_chat_history.html    # Chat session history
│   ├── ai_document_parser.html # AI document scan/parse view
│   ├── ai_insights.html        # AI fleet insights
│   ├── vehicle_tax.html        # Tax details list
│   └── tax_form.html           # Tax add/edit form
├── static/
│   ├── css/style.css       # Custom dark theme styles
│   └── js/script.js        # Sidebar toggle and flash auto-dismiss
├── uploads/            # User file uploads
├── exports/            # Generated export files
├── backups/            # Database backup files (local/ and gdrive/ subfolders)
├── client_secret.json  # Google OAuth client (required for GDrive sync)
└── token.json          # Google OAuth token (auto-generated after connect)
```

---

## Setup & Installation

### Prerequisites
- Python 3.9+
- Tesseract OCR installed (for the AI Document Parser) — default path `C:\Program Files\Tesseract-OCR\tesseract.exe`

### Install

```bash
cd vcms_aug-main
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate      # Linux/macOS
pip install -r requirements.txt
```

### Run

```bash
python app.py
```

Visit **http://localhost:5000**. The database (`vehicles.db`) is created automatically on first run.

### Windows One-Click Start
- `start_vcms.bat` — starts the server in a console window
- `start_vcms_silent.vbs` — starts it hidden in the background

### Load Sample Data (Optional)

```bash
python seed_data.py
```

This inserts 5 demo vehicles with varied expiry statuses for testing.

---

## Configuration

Environment variables override defaults in `config.py` and can be placed in a `.env` file (see `.env.example`):

| Variable | Purpose | Default |
|----------|---------|---------|
| `VCMS_SECRET_KEY` | Flask session secret key | `dev-secret-key-change-in-production` |
| `VCMS_DATABASE_URI` | SQLAlchemy database URI | `sqlite:///vehicles.db` |
| `VCMS_LOGIN_REQUIRED` | Require login for all pages | `true` |
| `VCMS_ADMIN_USER` | Admin login username | `admin` |
| `VCMS_ADMIN_PASSWORD` | Admin login password | `admin123` |
| `VCMS_AI_PROVIDER` | AI provider (`openrouter` or `gemini`) | `openrouter` |
| `VCMS_OPENROUTER_KEY` | OpenRouter API key | *(empty)* |
| `VCMS_OPENROUTER_MODEL` | OpenRouter model ID | `nvidia/llama-nemotron-embed-vl-1b-v2:free` |
| `VCMS_GEMINI_KEY` | Google Gemini API key | *(empty)* |
| `VCMS_GEMINI_MODEL` | Google Gemini model ID | `gemini-2.0-flash` |
| `VCMS_SMTP_SERVER` | SMTP server | `smtp.gmail.com` |
| `VCMS_SMTP_PORT` | SMTP port | `587` |
| `VCMS_EMAIL_REMINDERS_ENABLED` | Enable email reminders | `false` |
| `VCMS_EMAIL_REMINDER_HOUR` | Daily auto-reminder hour (24h) | `9` |
| `VCMS_GDRIVE_ENABLED` | Enable Google Drive sync | `false` |

> **Note:** AI keys/models, SMTP/Mailgun credentials, and Google Drive settings can also be configured interactively in Settings → persisted to `settings.json`.

### Settings Page
The `/settings` page offers **Test Connection** buttons for OpenRouter and Gemini, an SMTP test email send, Google Drive connect/disconnect, and gated saving of all credentials.

### Google Drive Sync
1. Create an OAuth Desktop client at Google Cloud Console and save it as `client_secret.json` in the project root.
2. In Settings → Connect, authorize the app.
3. Backups automatically sync to a `VCMS Backups` folder after vehicle writes (if auto-sync is enabled), keeping the newest 10 remote backups.

---

## Usage

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Overview of all vehicle compliance stats |
| Vehicle List | `/vehicles` | Search, filter, and manage all vehicles |
| Add Vehicle | `/vehicles/add` | Add a new vehicle record |
| Import | `/import` | Bulk import from Excel/CSV/JSON |
| Export | `/export` | Configure and download vehicle data |
| Reports | `/reports` | Generate compliance reports |
| Reminder Logs | `/reminders` | View sent/failed email reminders |
| Backup | `/backup` | Create, restore, download, or sync backups |
| Settings | `/settings` | AI / email / Google Drive configuration |
| Vehicle Tax | `/vehicles/<id>/tax` | View tax payment history |
| AI Chat | `/ai/chat` | Ask questions about your fleet |
| AI Document Parser | `/ai/parse-document` | Scan a document image/PDF, extract and apply vehicle data |
| AI Insights | `/ai/insights` | Fleet-wide compliance risk analysis |

### Default Login

- **Username**: `admin`
- **Password**: `admin123`

Change these via environment variables or directly in `config.py`.

---

## Routes Reference

### Auth
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/login` | GET/POST | Login |
| `/logout` | GET | Logout |

### Vehicles
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/vehicles` | GET | List / search / filter vehicles |
| `/vehicles/add` | GET/POST | Add vehicle |
| `/vehicles/<id>/edit` | GET/POST | Edit vehicle |
| `/vehicles/<id>` | GET | Vehicle detail view |
| `/vehicles/<id>/delete` | POST | Delete vehicle |
| `/vehicles/delete-all` | POST | Delete all vehicles |
| `/vehicles/<id>/print` | GET | Single-vehicle print view |
| `/vehicles/print?ids=1,2` | GET | Batch print |
| `/vehicles/print-qr?ids=1,2` | GET | Batch QR print |
| `/vehicles/<id>/qr` | GET | Download vehicle QR (PNG) |
| `/vehicles/<id>/qr-dates` | GET | QR detail view |

### Reminders
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/vehicles/<id>/whatsapp/<doc>` | GET | WhatsApp reminder (`all` for full details) |
| `/vehicles/<id>/whatsapp-expired` | GET | WhatsApp expired/expiring alert |
| `/vehicles/<id>/email-reminder` | POST | Send per-vehicle email reminder |
| `/vehicles/email-bulk` | POST | Bulk reminders to all vehicles |
| `/vehicles/email-selected` | POST | Reminders to selected vehicles |
| `/vehicles/email-all-details` | POST | Full details report per owner |
| `/reminders` | GET | Reminder log list |
| `/reminders/clear` | POST | Clear reminder logs |

### Import / Export / Reports
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/import` | GET/POST | Import vehicles |
| `/export` | GET | Export configuration page |
| `/export/run` | GET | Generate and download export |
| `/reports` | GET | Reports (scope via `?type=`) |

### Backup & Google Drive
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/backup` | GET/POST | Create/restore/download backups |
| `/backup/download/<path>` | GET | Download a backup file |
| `/backup/sync` | POST | Upload backup to Google Drive |
| `/backup/gdrive-list` | GET | List cloud backups (JSON) |
| `/backup/gdrive-restore` | POST | Restore from Google Drive |
| `/backup/sync-status` | GET | GDrive sync status (JSON) |
| `/settings/google/connect` | GET | Start GDrive OAuth flow |
| `/settings/google/callback` | GET | OAuth callback |
| `/settings/google/disconnect` | POST | Disconnect GDrive |

### AI
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ai/chat` | GET/POST | AI chat (optional `/<session_id>`) |
| `/ai/chat/history` | GET | Chat sessions list |
| `/ai/chat/<id>/delete` | POST | Delete a chat session |
| `/ai/parse-document` | GET/POST | OCR + AI document parsing |
| `/ai/scan-history/<id>` | GET | View a previous scan |
| `/ai/parse-document/add` | POST | Add/update vehicle from parsed data |
| `/ai/insights` | GET | AI fleet insights |

### API / Settings
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/vehicle/<id>` | GET | Vehicle data as JSON |
| `/api/check-duplicate` | GET | Duplicate check on a field |
| `/settings` | GET/POST | Application settings |
| `/settings/test-api` | POST | Test AI provider connection |
| `/settings/test-api-debug` | POST | Test AI connection with debug output |
| `/settings/test-email` | POST | Send a test email |
| `/settings/save-email` | POST | Save email settings |

### Tax Details
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/vehicles/<id>/tax` | GET | Tax history list |
| `/vehicles/<id>/tax/add` | GET/POST | Add tax detail |
| `/tax/<id>/edit` | GET/POST | Edit tax detail |
| `/tax/<id>/delete` | POST | Delete tax detail |

---

## Production Notes

This application uses simple session-based single-user authentication. For production or multi-user deployments, consider:

- **Flask-Login** with hashed passwords stored in the database (roles/ACLs)
- **Flask-WTF** for CSRF protection on all forms
- **PostgreSQL** or **MySQL** instead of SQLite for concurrent access
- **Gunicorn** or **uWSGI** as a production WSGI server
- **Nginx** as a reverse proxy with HTTPS
- Move `SECRET_KEY` and credentials to a secrets manager
- Add rate limiting, input sanitization, and audit logging for public-facing deployments