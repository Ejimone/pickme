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

## Stage 4 — Trips & real-time tracking ✅
- [x] Models: `Trip`, `TripStop`, `TripStopChild`, `LocationPing` (BigAutoField pk, `(trip, recorded_at)` index)
- [x] Channels (Redis layer) + `ws/trips/{trip_id}/` consumer (`JWTAuthMiddleware`, connect-time room authorization, driver-only writes)
- [x] REST fallback ping endpoint (`POST /trips/{id}/location/`) + `GET /trips/{id}/location/latest/`
- [x] ETA recalculation task (Distance Matrix behind `MAPS_BACKEND=fake|google`, per-trip Redis lock throttle)
- [x] Nightly `LocationPing` cleanup (batched deletes, `LOCATION_PING_RETENTION_DAYS`)
- [x] Tests: consumer auth rejection (4001/4003), ETA task + throttle, ping cleanup, trip scoping/lifecycle/stop transitions

## Stage 5 — Pickup events ✅
- [x] `PickupEvent` model (in the `trips` app; unique `(child, date)`, `date`/`(child,date)` indexes) + `PATCH /pickup-events/{id}/` override
- [x] Daily generation task (`generate_daily_pickup_events` beat) + signal cascade: trip→in_progress ensures a row per child (en_route), stop arrived → arrived, `TripStopChild.picked_up_at` → picked_up
- [x] "Today" aggregation endpoint (`GET /pickup-events/?date=&family=`, one row per child across a family's schools, defaults to today)

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
