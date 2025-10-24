<p align="center">
  <h1 align="center">Hackathon Registration & Operations Platform</h1>
  <p align="center">
    Modern, extensible and privacy‑aware Django backend for managing hackathon applications, teams, logistics and stats.
  </p>
</p>

---

## 1. Overview

HackAssistant is a modern re‑implementation of the original
[HackAssistant/registration](https://github.com/HackAssistant/registration) and is
heavily based on the upstream
[HackAssistant/hackassistant](https://github.com/HackAssistant/hackassistant)
project. Full credit to the HackAssistant maintainers and contributors.
This fork focuses on:

- Maintainability (modular apps, mixins, documented utilities)
- Privacy & compliance (age anonymization, explicit consents)
- Extensibility (pluggable apps: friends/teams, messages, meals, stats, tables)
- Operational visibility (stats & tables, export formats, cron jobs)
- Security hardening (brute force protection, admin honeypot, CSP, password history, reCAPTCHA)

This repository powers the official registration and attendee operations platform for **HackMTY** and includes event‑specific tweaks.

Highlights adapted for HackMTY:
- Consent ordering tuned for local policies first
- Age privacy layer (integer age → synthetic birth_date)
- Mandatory phone number & stricter validations for on‑site logistics
- Centralized Level of Study synced to profile
- Judge onboarding requires invite codes, captures judge specialization, and auto-enrols each judge into the review roster so organizers see them immediately.
- Admissions workflow with Invite, Waitlist and Reject actions (distinct statuses and emails)
- Friends (teams) with capacity and Devpost project link capture (visible starting on the event day)
- Event banners and date‑gated disclaimers (e.g., no re‑entry window)

---

## 2. Features

Accounts & Security
- Email registration & login (django‑allauth)
- Email verification & password reset
- Password reuse prevention (history) + composition validators
- Brute force mitigation with django‑axes (IP cool‑off)
- Admin honeypot and CSP defaults
- Judge registration flow enforces invite codes and immediate email verification to keep the roster controlled.

Applications
- Configurable application types (Hacker, Volunteer, Mentor, Sponsor)
  - Hidden types with token-gated apply links for private programs (e.g., Sponsor). Rotate tokens from admin.
- Judge application type stays hidden from applicants but is auto-created for every Judge group member, keeping the review roster up-to-date without manual data entry.
- Extra dynamic fields stored as JSON (`form_data`) + file uploads with overwrite
- Promotional codes, custom consents, MLH‑style policy capture
- Invite / Waitlist / Reject organizer actions and tailored emails

Teams (Friends)
- Join by code, leave, capacity limit (configurable)
- Team closed when any member is invited/confirmed/attended
- Full teams can attach a Devpost URL (editing enabled for team members; card visible from the event start date)

Organizer tooling
- Review list and actions, stats with filters, exportable tables
- Judge application tab with "judge type" filter surfaced alongside other application types for fast slicing.
- Admin panel for teams: list by code, counts, filters, CSV export, deep links

Event ops
- Messages and meals sub‑apps (optional)
- Cron jobs for invitation expiry and housekeeping

UI/UX
- Bootstrap 5 forms and layout helpers
- Light/Dark themes (both available)
- Dedicated judge onboarding flow with direct access to the scoring dashboard

---

## 3. Repository structure (key directories)

```
app/                Global project (settings, urls, templates, middlewares, logging, theme)
application/        Application model & type‑specific forms (Hacker, Mentor, etc.)
user/               Custom user model, forms, profile logic, choices
review/             Review workflows (organizer tools)
stats/              Statistics generation & filtering
tables/             Table utilities & views
friends/            Teaming (join/leave, capacity, Devpost)
event/              Event domain (messages, meals sub‑apps)
files/              Uploaded resume & file storage
staticfiles/        Collected & hashed static assets (production)
production/         Production docker-compose & scripts
```

---

## 4. Tech stack

- Django 4.2, Python 3.9/3.10
- Auth: django‑allauth; JWT/OIDC provider mode available (django‑jwt‑oidc)
- Security: django‑axes, admin‑honeypot, CSP, password validators, reCAPTCHA
- UI: Bootstrap 5 (django‑bootstrap5)
- Tables/Export: django‑tables2 + tablib formats
- Email: AnyMail (Mandrill) with file‑based fallback in DEBUG
- Scheduling: django‑crontab
- Assets: django‑compressor, libsass, ManifestStaticFilesStorage

---

## 5. Quick start (Docker)

Prerequisites: Docker, Docker Compose.

```bash
git clone https://github.com/HackAssistant/hackassistant.git
cd hackassistant
./install.sh             # sets up virtualenv, installs deps, applies migrations (ok to run with docker)
docker-compose up        # launches dev server at http://localhost:8000
```

Common dev commands:

```bash
docker-compose run python manage.py makemigrations
docker-compose run python manage.py migrate
docker-compose run python manage.py createadmin
docker-compose run python -m pip install <library>
```

Static & compress (optional locally):

```bash
docker-compose run python manage.py collectstatic --noinput
docker-compose run python manage.py compress --force
```

---

## 6. Quick start (Local venv)

Prerequisites: Python 3.9+.

```bash
git clone https://github.com/HackAssistant/hackassistant.git
cd hackassistant
python -m venv env
source env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py createadmin   # creates initial organizer admin
python manage.py runserver 0.0.0.0:8000
```

---

## 7. Environment variables (selected)

| Variable | Purpose | Default / Notes |
|----------|---------|-----------------|
| SECRET_KEY | Django secret key | required |
| PROD_MODE | Toggle production security flags | False |
| ALLOWED_HOSTS | Comma separated hosts | empty (+ localhost in DEBUG) |
| DB_ENGINE | sqlite3 / postgresql / mysql / oracle | sqlite3 |
| DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT | DB credentials (non‑sqlite) | — |
| GOOGLE_RECAPTCHA_SITE_KEY / GOOGLE_RECAPTCHA_SECRET_KEY | reCAPTCHA keys | optional |
| AXES_FAILURE_LIMIT | Brute force attempt limit | default 15 here |
| AXES_ENABLED | Enable django‑axes | not DEBUG |
| ADMIN_URL | Secret admin path | secret/ |
| OIDC_DISCOVERY_ENDPOINT | JWT/OIDC provider discovery | local default |
| HACKATHON_START_DATE / HACKATHON_END_DATE | dd/mm/YYYY | drives event gating (e.g., disclaimers, Devpost card) |

See `app/settings.py` and `app/hackathon_variables.py` for more.

---

## 8. Model & workflows

User (`user.User`)
- Email is the primary credential; extended demographics; synthetic birth_date from age input.

Application (`application.Application`)
- One per type and edition; extra fields inside `form_data` JSON. Files stored under `<edition>/<type>/<field>/<name>_<uuid>.<ext>`.
- Organizer actions support Invite, Waitlist, Reject with dedicated emails.
- Cancelling a Hacker application removes the user from their team and frees a spot.

Teams (Friends)
- Join by code; leave any time; team closes if any member is invited/confirmed/attended.
- Capacity enforced via `FRIENDS_MAX_CAPACITY`.
- When full, a Devpost URL card appears starting on the event day for members to add/edit the project link.

Stats & Tables
- Aggregated metrics and exportable tables for operational insight.

---

## 9. Security & privacy

- Axes login throttling (5‑minute cool‑off) and configurable attempt limit
- Admin honeypot, CSP headers, secure cookies (when PROD_MODE=true)
- Password history and composition validators
- reCAPTCHA protection

---

## 10. Cron jobs (django‑crontab)

Typical jobs include invitation expiry and housekeeping. Register on boot via `python manage.py crontab add`.

List / remove:
```bash
python manage.py crontab show
python manage.py crontab remove
```

---

## 11. Deployment notes

- Always run the latest migrations before rolling out judge tooling. Migration `user.0014_user_judge_type` backfills confirmed `Application` rows for existing judges so they appear in review tables. Execute `python manage.py migrate` during deploys and spot-check the review dashboard afterward to ensure counts and judge types look correct.
- Prefer a reverse proxy (nginx/traefik) in front of gunicorn.
- Recommended 5 MB upload limit and friendly 413 redirect:

```nginx
client_max_body_size 5m;
error_page 413 =302 /upload-too-large/;
```

- Example production compose in `production/docker-compose.yml`.

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 413 on upload | Proxy limit | Set `client_max_body_size` and friendly redirect |
| Missing static | Not collected | `manage.py collectstatic` |
| 403 on /application for organizers | Intentional to keep reviewer UI clean | Use reviewer pages or adjust `ApplicationHome.dispatch` |

| Hidden Sponsor link returns 404 | Missing/invalid token | Use the share link shown in Admin > Application type > Sponsor, or rotate token via action |

---

## 13. Contributing

1. Fork and branch (`feature/<short>`)
2. Keep patches focused; update docs
3. Run linters and Django checks
4. Open PR with context and screenshots (for UI)

---

## 14. License & security

Distributed under the project LICENSE. For security issues, follow `SECURITY.md` and avoid public issues.

---

## 15. Quick commands

```bash
# Dev up (docker)
docker-compose up

# Migrations
docker-compose run python manage.py makemigrations
docker-compose run python manage.py migrate

# Create admin
docker-compose run python manage.py createadmin

# Static & compress
docker-compose run python manage.py collectstatic --noinput
docker-compose run python manage.py compress --force

# Cron jobs
docker-compose run python manage.py crontab show
```

---

Happy hacking! 🚀

---

## 16. Acknowledgements

- This project is built on the shoulders of
  [HackAssistant/hackassistant](https://github.com/HackAssistant/hackassistant)
  and the original
  [HackAssistant/registration](https://github.com/HackAssistant/registration).
  Huge thanks to all maintainers and contributors of the upstream projects.
