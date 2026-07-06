# Decisions Log

Choices made where the spec docs (`instructions/`) were silent.

## Stage 0

- **Python 3.13 locally** (spec says 3.12): the pre-created venv is 3.13 and
  Django 5.2 supports it. The Dockerfile pins `python:3.12-slim` to match the
  spec for deployed environments.
- **Health check path**: `GET /api/v1/health/` (API-DESIGN.md doesn't list
  one). Public, checks a DB round-trip.
- **JIT-provisioned users get a placeholder email** —
  `<clerk_user_id>@pending.clerk.local` — because Clerk session JWTs don't
  carry an email claim by default and `users.email` is NOT NULL + unique.
  The `user.created`/`user.updated` webhook overwrites it with the real one.
- **Custom user model** subclasses `AbstractBaseUser` + `PermissionsMixin`
  with `USERNAME_FIELD = email` and unusable passwords (Clerk owns
  credentials). `createsuperuser` still works for local Django admin with a
  synthetic `clerk_user_id`.
- **`aud` claim not verified** on Clerk session tokens (they don't set one);
  instead the `azp` claim is checked against `CLERK_AUTHORIZED_PARTIES` when
  that env var is set, per Clerk's own guidance.
- **JWKS caching** uses PyJWT's `PyJWKClient` with `cache_keys=True` and a
  1-hour lifespan (module-level singleton) instead of a hand-rolled cache.
- **Webhook returns 204** for all handled *and* unknown event types so Clerk
  stops retrying; only signature failures get a 400.
- **`user.deleted` hard-deletes** the local row. Once family/child FKs exist
  (Stage 1) this will be revisited — likely switch to deactivation.
- **Permission classes resolve models via `apps.get_model` at request time**
  because `families`/`carpool` models don't exist until Stages 1 and 3.
- **`daphne` runs the dev server** (via `INSTALLED_APPS`), uvicorn serves in
  Docker — both hit the same `config.asgi:application`.
- **`.env.docker` is committed** (compose needs it; contains only dev-local
  values, no secrets). `.env` stays gitignored.

## Stage 1

- **`FamilyInvite` model added** — DATABASE-SCHEMA.md's 25 tables don't
  include an invite table, but Stage 1/API-DESIGN require an email-invite →
  accept flow. Fields: family, email, invited_by, unique `token` (UUID),
  status (`pending`/`accepted`/`revoked`), timestamps.
- **Invite acceptance is by token possession** (`POST
  /api/v1/family-invites/accept/ {"token"}`), no email match required —
  JIT-provisioned users may still carry a placeholder email when they
  accept. API-DESIGN.md doesn't define the accept endpoint; this one was
  chosen.
- **Invite email** goes through Django's email framework with the console
  backend by default (`EMAIL_BACKEND` env var swaps in a real provider
  later).
- **`user.deleted` now deactivates** (`is_active=False`) instead of
  hard-deleting — `families.created_by` is `on_delete=PROTECT` and pickup
  history must survive account deletion. Supersedes the Stage 0 decision.
- **`Child.is_active` soft-delete flag added** per the schema doc's cascade
  notes; `DELETE /children/{id}/` flips it and the API filters it out.
- **`Child.school` is `on_delete=SET_NULL`** — schema says schools should
  never really be deleted; if one is removed, children shouldn't vanish.
- **Family renames and member removal are owner-only** (PLAN.md treats
  members as equal for children/schedules; ownership actions stay with the
  owner per API-DESIGN.md). The owner's own membership row can't be removed.
- **`School.early_dismissal_days` format defined** as a JSON object mapping
  Python weekday ints (as strings, 0=Monday) to `"HH:MM"`, e.g.
  `{"2": "13:30"}` = Wednesdays dismiss at 1:30pm. Validated in the
  serializer.
- **School PATCH is open to any authenticated user** per API-DESIGN.md
  (shared reference data; no ownership concept on schools in v1).

## Stage 2

- **`Activity` lives in the `families` app** (it's child-scoped data, like
  `Child`); the resolution logic lives in `schools/services.py` per the
  build prompt and imports nothing at module scope that would couple the
  apps.
- **`Activity.day_of_week` uses Python's weekday convention** (0=Monday …
  6=Sunday), matching `date.weekday()` and the
  `School.early_dismissal_days` keys. The schema doc says only "0–6".
- **Resolution semantics** (`resolve_effective_pickup_time(child, date)`):
  weekends and holiday exceptions (`dismissal_time=None`) yield no base
  dismissal; an activity that day still produces a pickup time on its own
  (kids get dropped off at practice on days off). No school assigned, or
  no school day + no activity → `None`. Comparisons happen in the school's
  IANA timezone; the return value is a UTC-aware datetime.
- **Activity permission scoping** reuses `IsFamilyMember` via a
  `family_id` property on `Activity`; flat `/activities/{id}/` routes are
  additionally queryset-scoped to the user's families (others 404).
