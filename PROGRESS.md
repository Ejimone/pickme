# Progress — mirrors instructions/BUILD-STAGES.md

## Stage 0 — Scaffold ✅
- [x] Django project (`config/`) + apps: `accounts`, `families`, `schools`, `carpool`, `trips`, `chat`, `notifications`, `core`
- [x] Postgres connection, environment-based settings (django-environ)
- [x] Clerk JWT authentication class (JWKS fetch + cache, RS256 verify, JIT-provision `User`)
- [x] Clerk webhook endpoint (`/api/v1/webhooks/clerk/`) with Svix signature verification (`user.created`/`user.updated`/`user.deleted`)
- [x] Base permission classes: `IsFamilyMember`, `IsCarpoolGroupMember`, `IsCarpoolGroupAdmin`
- [x] Health check endpoint (`/api/v1/health/`), pytest config, 16 tests passing
- [x] `docker-compose.yml` (db, redis, web, worker, beat) + `Dockerfile`

## Stage 1 — Core domain ✅
- [x] Models: `User` (Stage 0), `Family`, `FamilyMember`, `FamilyInvite`, `School`, `SchoolCalendarException`, `Child`
- [x] Serializers + viewsets + routing (`/families/`, `/children/`, `/schools/`, calendar exceptions)
- [x] Family invite flow (email invite → accept by token)
- [x] Tests: family-scoped access control (user A can't see family B's children), invite flow end-to-end, owner-only actions

## Stage 2 — Activities ✅
- [x] Model + CRUD for `Activity` (`/children/{id}/activities/`, `/activities/{id}/`)
- [x] "Today" effective-pickup-time resolution in `schools/services.py` (default → early-dismissal weekday → calendar exception → later activity end, tz-aware)

## Stage 3 — Carpool & rotation engine ✅
- [x] Models: `CarpoolGroup`, `CarpoolGroupMember`, `CarpoolRotationRule`, `CarpoolRotationOrder`, `CarpoolAssignment`, `CarpoolSwapRequest`
- [x] Rotation algorithm (round-robin + weighted-by-repetition, never-overwrite, slot-anchored to `start_date`)
- [x] Swap request flow (request → accept/reject) + hourly `expire_stale_swap_requests` beat task
- [x] Tests: rotation correctness across multi-week weighted ranges w/ pre-existing manual assignments, swap flow end-to-end, group scoping

## Stage 4 — Trips & real-time tracking
- [ ] Models: `Trip`, `TripStop`, `TripStopChild`, `LocationPing`
- [ ] Channels (Redis layer) + `ws/trips/{trip_id}/` consumer
- [ ] REST fallback ping endpoint
- [ ] ETA recalculation task (Distance Matrix, throttled)
- [ ] Nightly `LocationPing` cleanup
- [ ] Tests: consumer auth rejection, ETA task, ping cleanup

## Stage 5 — Pickup events
- [ ] Model + CRUD for `PickupEvent`
- [ ] Daily generation task/signal
- [ ] "Today" aggregation endpoint

## Stage 6 — Chat
- [ ] Models: `ChatThread`, `ChatMessage`, `ChatReadReceipt`
- [ ] `ws/chat/{thread_id}/` consumer
- [ ] REST history endpoint (cursor pagination)

## Stage 7 — Notifications
- [ ] Models: `Notification`, `NotificationPreference`, `DeviceToken`
- [ ] Dismissal reminder beat task
- [ ] Expo push fan-out task
- [ ] Notification triggers wired

## Stage 8 — Safety
- [ ] `SOSAlert` model + immediate fan-out (WebSocket + push)

## Stage 9 — Media, polish, deploy
- [ ] Cloudinary integration
- [ ] OpenAPI schema export (`schema/openapi.yaml`)
- [ ] DigitalOcean App Platform deploy
