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

## Stage 3

- **Group creation payload includes `family`** — API-DESIGN.md doesn't say
  which of the creator's families joins the new group, and users can belong
  to several. The named family becomes the group's first `admin` member;
  the same pattern applies to `POST /carpool-groups/join/`.
- **Invite codes** are 8 chars from an unambiguous A–Z/2–9 alphabet,
  generated server-side, unique.
- **`PUT rotation-rule` replaces rule + order atomically**
  (`update_or_create` + delete/bulk-create of order entries). The separate
  `reorder` endpoint suggested in SYSTEMS-DEEP-DIVE.md is covered by this
  PUT (a reorder is just a PUT with new positions), so it wasn't added as
  a distinct route.
- **`round_robin` ignores weights** (everyone gets one slot per cycle);
  `weighted` expands by repetition exactly per the spec pseudocode;
  `manual_only` generates nothing.
- **Slot anchoring**: the engine counts applicable dates from
  `rule.start_date` up to the window start, so generating week 2 alone
  yields the same drivers as generating weeks 1–2 together. Holidays
  (exception with null dismissal) are not applicable dates and consume no
  slot; existing assignments do consume their slot (per the spec's
  `slot_number += 1` on skip).
- **Confirm sets `driver_user` to the confirming user** ("specific person,
  set once confirmed" per the schema doc) and only works from
  `suggested`/`confirmed` states.
- **One pending swap per assignment**; requesting flips the assignment to
  `swap_pending`. Reject/expiry release it back to `confirmed` when a
  `driver_user` is set, else `suggested`. Accept reassigns
  `driver_family`/`driver_user` on that one row only — rotation order is
  never re-anchored (per SYSTEMS-DEEP-DIVE.md).
- **`SWAP_REQUEST_EXPIRY_HOURS` (default 48)** drives the hourly
  `expire_stale_swap_requests` beat task; the schedule is declared in
  `CELERY_BEAT_SCHEDULE` (django-celery-beat's DatabaseScheduler imports
  it on startup).
- **Removing the group's only admin is blocked** — a group must always
  have at least one admin.

## Stage 4

- **`Trip.driver` is `on_delete=CASCADE`** — the schema doc's cascade section
  doesn't cover trips; a deleted account's trips (and their pings, per the
  doc's "no value in orphaned pings") go with it. Users are deactivated, not
  deleted, in practice (Stage 1 decision), so this path is theoretical.
- **No cancel endpoint** — the `cancelled` status exists in the schema but
  API-DESIGN.md defines only `start`/`end`. Cancellation can be added later
  without schema changes.
- **Stop `picked_up` accepts an optional `children` subset** in the PATCH
  body (defaults to all children at the stop) so a driver can record a
  partial pickup; `TripStopChild.picked_up_at` rows are saved individually
  so the Stage 5/7 cascade signal fires per child.
- **Trip creation validates child visibility**: every child on a stop must
  be in one of the driver's families or in a family sharing a carpool group
  with the driver — prevents referencing arbitrary child UUIDs.
- **WS auth token is a query param** (`ws/trips/{id}/?token=...`) — the docs
  allow query param or first-message payload; query param keeps the
  consumer's connect-time authorization synchronous and lives in a reusable
  `accounts.middleware.JWTAuthMiddleware`. Close codes: 4001 unauthenticated,
  4003 authenticated but not a trip participant.
- **ETA throttle lock is acquired by the dispatcher** (`record_ping`), not
  inside the task, exactly per SYSTEMS-DEEP-DIVE.md's write path: `SET NX EX
  {ETA_THROTTLE_SECONDS}` on `eta_lock:{trip_id}`; a held lock skips dispatch
  entirely (a fresher ping will trigger the next one).
- **ETA destination uses stored coordinates** — `School.lat/lng` and
  `Activity.location_lat/lng` already exist in the schema, so the Distance
  Matrix call uses coordinates, not address strings; stops without
  coordinates simply never get an ETA (no geocoding fallback in v1).
- **`MAPS_BACKEND=fake|google`** selects the Distance Matrix client; the
  fake is deterministic (60s per 0.01°) so tests/dev never hit the real API.
  The Google client prefers `duration_in_traffic` when present.
- **REST fallback ping requires an `in_progress` trip**; the WS path only
  requires being the driver (the trip room is already scoped on connect).

## Stage 5

- **`PickupEvent` lives in the `trips` app**, not a new `pickups` app — the
  working-rule app list is fixed (8 apps, no `pickups`), and `PickupEvent`
  FKs `TripStopChild` (trips) and `CarpoolAssignment` (carpool), both of
  which `trips` already depends on. Routes stay at `/api/v1/pickup-events/`.
- **`scheduled_time` is nullable** (schema implies non-null). A trip can run
  on a day `resolve_effective_pickup_time` returns `None` for (e.g. an
  ad-hoc pickup); rather than fabricate a time, the row is created with a
  null `scheduled_time` and backfilled if a real time later resolves.
- **Cascade is a signal chain in `trips/signals.py` delegating to
  `trips/pickups.py`** (thin signals rule): `Trip` post_save at
  `in_progress` → `ensure_pickup_events_for_trip` (one row per child, method
  `carpool` when the trip has a group, status `en_route`); `TripStop`
  post_save → `sync_stop_status` (en_route/arrived propagate, never
  downgrading a picked_up row); `TripStopChild.picked_up_at` set →
  `mark_child_picked_up`. The Notification fan-out on picked_up is deferred
  to Stage 7. Trip-start marks stops en_route via a bulk `.update()` (no
  per-row signal), so the en_route status is set directly on the events.
- **Auto-derived `pickup_method` is `parent` or `carpool` only** — the other
  choices (`aftercare`/`bus`/`walker`) are manual overrides via PATCH.
  `carpool` is chosen when a non-cancelled `CarpoolAssignment` covers the
  child's group+school+date, or (for trip-generated rows) when the trip
  carries a carpool group.
- **Daily generation is a single global beat task** iterating active
  children with a school and a resolvable pickup that day — fine at this
  scale; idempotent via `get_or_create` on `(child, date)`.
- **"Today" list defaults `date` to `timezone.localdate()`** when the query
  param is absent; detail/PATCH are not date-filtered.
- **Generation never downgrades an existing row** — `ensure_pickup_event`
  only backfills an empty `trip_stop_child`/`scheduled_time`; status and a
  manual method override set by a user are preserved on re-runs.

## Stage 6

- **Threads are auto-created by signal**, not via a POST endpoint
  (API-DESIGN.md lists no thread-create route): `chat/signals.py` fires
  `get_or_create` on `CarpoolGroup` creation (a `carpool_group` thread) and
  `Trip` creation (a `trip` "today's run" thread, carrying the trip's
  carpool group). Partial unique constraints (`context_type`-conditioned)
  keep it to one thread per group and one per trip.
- **`ChatConsumer` broadcast types use dots** (`message.new`/`message.read`)
  to match API-DESIGN.md; Channels maps the dotted `type` to the
  `message_new`/`message_read` handler methods (it replaces `.` with `_`).
  Client→server events are `message.send`/`message.read`.
- **`post_message` / `mark_read` live in `chat/services.py`** and are shared
  by the consumer and the REST fallback so both persist and broadcast
  identically (same pattern as `trips.services.record_ping`).
- **"Mark read up to a message"** bulk-creates `ChatReadReceipt` rows for
  every message in the thread at or before the target's `created_at` that the
  user hasn't already receipted (`bulk_create(ignore_conflicts=True)`) —
  idempotent, and honors the per-message `(message, user)` unique constraint
  in the schema rather than storing only a high-water mark.
- **History uses the shared `TimeOrderedCursorPagination`** (`-created_at`),
  to which a `page_size` query param + `max_page_size=100` were added (it
  previously had a fixed page size); this also benefits location-ping
  history.
- **Thread access = carpool-group membership or trip participation**
  (`threads_visible_to`), reused by the list queryset, `IsThreadParticipant`,
  and the consumer's connect check — mirrors the trips visibility helper.
