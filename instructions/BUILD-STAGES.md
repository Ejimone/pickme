# Build Stages — School Pickup Coordinator Backend

Meant to be worked through one stage at a time. Each stage should end in a working, migrated, tested state before moving to the next.

## Stage 0 — Scaffold
- Django project (`config/`) + apps: `accounts`, `families`, `schools`, `carpool`, `trips`, `chat`, `notifications`, `core`
- Postgres connection, environment-based settings (django-environ)
- Clerk JWT authentication class (fetch + cache JWKS, verify RS256, JIT-provision `User` as fallback)
- Clerk webhook endpoint (`/webhooks/clerk/`) with Svix signature verification to keep `User` in sync on `user.created`/`user.updated`/`user.deleted`
- Base permission classes: `IsFamilyMember`, `IsCarpoolGroupMember`, `IsCarpoolGroupAdmin`
- Health check endpoint, CI-ready test config

## Stage 1 — Core domain
- Models: `User`, `Family`, `FamilyMember`, `School`, `SchoolCalendarException`, `Child`
- Serializers + viewsets + routing for all of the above
- Family invite flow (email invite → accept)
- Tests: family-scoped access control (user A can't see family B's children)

## Stage 2 — Activities
- Model + CRUD for `Activity`
- "Today" resolution logic: given a child + date, compute the effective pickup time (school dismissal, minus calendar exception override, plus any activity end time if later)

## Stage 3 — Carpool & rotation engine
- Models: `CarpoolGroup`, `CarpoolGroupMember`, `CarpoolRotationRule`, `CarpoolRotationOrder`, `CarpoolAssignment`, `CarpoolSwapRequest`
- Rotation algorithm (round-robin first — simplest correct version, weighted later): given a rule + date range, produce suggested assignments skipping dates already manually set
- Swap request flow + Celery task to auto-expire stale requests
- Tests: rotation correctness across a multi-week range, swap flow end-to-end

## Stage 4 — Trips & real-time tracking
- Models: `Trip`, `TripStop`, `TripStopChild`, `LocationPing`
- Django Channels setup (ASGI, Redis channel layer)
- WebSocket consumer for `ws/trips/{trip_id}/` with JWT auth on connect + room membership check
- REST fallback ping endpoint
- Celery task: ETA recalculation via Google Distance Matrix, throttled per trip
- Celery beat: nightly `LocationPing` cleanup
- Tests: consumer auth rejection, ETA task, ping cleanup

## Stage 5 — Pickup events
- Model + CRUD for `PickupEvent`
- Daily generation task/signal: when a trip starts or a plain (non-carpool) pickup day arrives, ensure a `PickupEvent` row exists per child
- "Today" aggregation endpoint pulling across all of a family's children/schools

## Stage 6 — Chat
- Models: `ChatThread`, `ChatMessage`, `ChatReadReceipt`
- WebSocket consumer for `ws/chat/{thread_id}/`
- REST history endpoint (cursor pagination)

## Stage 7 — Notifications
- Models: `Notification`, `NotificationPreference`, `DeviceToken`
- Celery beat: dismissal reminders per school/child
- Celery task: push fan-out via Expo push service
- Wire up notification triggers: driver arrived, swap request, chat message, schedule change

## Stage 8 — Safety
- Model: `SOSAlert`
- Immediate fan-out (bypass normal notification queue — this one should be as close to real-time as possible) to all guardians tied to the active trip/group
- WebSocket + push dual delivery

## Stage 9 — Media, polish, deploy
- Cloudinary integration for `Child.photo_url` and `ChatMessage.attachment_url`
- OpenAPI schema generation (drf-spectacular) — export once stable, this becomes the frontend's contract
- Deploy to DigitalOcean App Platform (web process + Channels/ASGI process + Celery worker + Celery beat as separate components, Redis + Postgres as managed add-ons)
- Once deployed and the schema's exported, that's the right point to come back and do frontend data-layer planning against the real contract instead of a guessed one.
