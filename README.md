# School Pickup Coordinator — Backend

Django + DRF backend for a family school-pickup coordination app: dismissal
schedules, carpool rotations, live GPS trip tracking, chat, notifications,
and SOS alerts. Spec lives in [instructions/](instructions/); build order in
[instructions/BUILD-STAGES.md](instructions/BUILD-STAGES.md); running status
in [PROGRESS.md](PROGRESS.md).

## Stack

Python 3.12+, Django 5.2, DRF, PostgreSQL (psycopg 3), Redis,
Django Channels, Celery + Beat, Clerk (auth), drf-spectacular.

## Local setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in Clerk values when you have them

docker compose up -d db redis   # Postgres + Redis
python manage.py migrate
python manage.py runserver      # or: uvicorn config.asgi:application
pytest
```

Full stack in Docker (web + celery worker + beat): `docker compose up`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | prod | Django secret key |
| `DEBUG` | no (default `False`) | Debug mode |
| `ALLOWED_HOSTS` | prod | Comma-separated hosts |
| `DATABASE_URL` | yes | Postgres DSN, e.g. `postgres://user:pass@host:5432/db` |
| `REDIS_URL` | yes | Redis DSN (Celery broker + channel layer) |
| `CELERY_TASK_ALWAYS_EAGER` | no | Run tasks inline (dev/tests) |
| `CLERK_ISSUER` | yes | Clerk instance issuer URL (JWT `iss`) |
| `CLERK_JWKS_URL` | no | Defaults to `$CLERK_ISSUER/.well-known/jwks.json` |
| `CLERK_AUTHORIZED_PARTIES` | no | Allowed JWT `azp` origins, comma-separated |
| `CLERK_WEBHOOK_SIGNING_SECRET` | yes | Svix secret for `/api/v1/webhooks/clerk/` |

## API

- Base path `/api/v1/`, `Authorization: Bearer <clerk_session_jwt>`
- Errors: `{"error": {"code", "message", "details"}}`
- `GET /api/v1/health/` — public health check
- `POST /api/v1/webhooks/clerk/` — Clerk user sync (Svix-signed)

A curl walkthrough of the full flow (create family → add child → carpool →
rotation → confirm) will land here once those stages exist.
