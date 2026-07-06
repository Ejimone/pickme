

---

You are building the backend for **School Pickup Coordinator**, a family school-pickup coordination app (dismissal schedules, carpool rotations, live GPS trip tracking, chat, notifications, SOS alerts).

## Source of truth

Read these docs in `docs/` before writing any code, in this order:
1. `PLAN.md` — architecture, tech stack, roles, key decisions
2. `DATABASE-SCHEMA.md` — all 25 tables with exact fields, constraints, indexes, cascade rules
3. `API-DESIGN.md` — every REST endpoint, WebSocket channel/event, Celery task, error envelope, pagination conventions
4. `SYSTEMS-DEEP-DIVE.md` — Celery task idempotency patterns, Channels consumer authorization, the rotation engine algorithm (implement it exactly as specified, including the never-overwrite rule), and the trip lifecycle signal cascade
5. `BUILD-STAGES.md` — the stage order to follow

These docs are the spec. Where the docs are silent, use standard Django/DRF conventions and note the decision in a `DECISIONS.md` file as you go. Where docs appear to conflict, stop and ask me rather than guessing.

## Stack (fixed, do not substitute)

- Python 3.12, Django 5.x, Django REST Framework
- PostgreSQL (use psycopg 3), Redis
- Django Channels + channels_redis for WebSockets
- Celery + Celery Beat (Redis broker), django-celery-beat for DB-backed schedules
- Clerk for auth: custom DRF authentication class verifying Clerk session JWTs via JWKS (cache the JWKS), JIT-provision local `User` on first request; `/api/v1/webhooks/clerk/` endpoint with **Svix signature verification** handling `user.created`/`user.updated`/`user.deleted`
- drf-spectacular for OpenAPI schema
- django-environ for settings; no secrets in code, `.env.example` with every required variable documented
- pytest + pytest-django + pytest-asyncio for tests
- Cloudinary via signed upload from backend for media endpoints
- Google Maps Distance Matrix for ETA (wrap in a service module with a fake/mock implementation selectable via env var so tests and local dev never hit the real API)

## Working rules

1. **Work stage by stage per `BUILD-STAGES.md`.** Complete a stage — models, migrations, serializers, views, URLs, permissions, tests all passing — before starting the next. Commit at each stage boundary with a message like `stage-3: carpool + rotation engine`.
2. **Tests are not optional.** Each stage's spec lists required tests; write them. Minimum bar overall: permission/scoping tests for every resource (user A must never see family B's data), rotation engine correctness across a multi-week weighted range with pre-existing manual assignments, Channels consumer connect-authorization rejection, swap request flow end to end, and the pickup cascade (TripStopChild.picked_up_at → PickupEvent → Notification).
3. **Project layout**: `config/` for settings/asgi/celery, apps: `accounts`, `families`, `schools`, `carpool`, `trips`, `chat`, `notifications`, `core` (shared permissions, pagination, error envelope handler).
4. **API conventions from API-DESIGN.md are binding**: `/api/v1/` prefix, the exact error envelope shape, PageNumberPagination default with CursorPagination for chat messages, membership-scoped permissions everywhere.
5. **UUID primary keys** everywhere except `LocationPing` (BigAutoField) — per the schema doc.
6. **Times in UTC** in the DB; `School.timezone` (IANA) drives local resolution. The "resolve effective pickup time for a child on a date" function (school default → calendar exception override → later activity end time) should be one well-tested pure function in `schools/services.py`.
7. **Signals stay thin and live in each app's `signals.py`**; the consumer never writes to more than the ping/status tables directly — cascades go through signals per SYSTEMS-DEEP-DIVE.md.
8. **Docker**: provide `docker-compose.yml` for local dev (postgres, redis, web via uvicorn for ASGI, celery worker, celery beat) and a production-ready `Dockerfile`. The whole stack must come up with `docker compose up` and pass `pytest` inside the web container.
9. After the final stage, export the OpenAPI schema to `schema/openapi.yaml` — this becomes the frontend contract.
10. Keep a running `PROGRESS.md` checklist mirroring BUILD-STAGES.md, ticking items as they land.

## Definition of done

- All stages in BUILD-STAGES.md complete, `pytest` green, `docker compose up` works from a clean clone
- `schema/openapi.yaml` exported and committed
- README with setup instructions, env var table, and a curl walkthrough of one full flow (create family → add child → create carpool group → generate rotation → confirm assignment)
- No TODOs left in code without a matching entry in DECISIONS.md

Start with Stage 0. Before writing code, print a short plan of the files you'll create for Stage 0 so I can sanity-check the structure.
