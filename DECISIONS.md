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
