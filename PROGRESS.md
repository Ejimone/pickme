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

## Stage 6 — Chat ✅
- [x] Models: `ChatThread`, `ChatMessage`, `ChatReadReceipt` (partial-unique thread per group/trip, `(thread, created_at)` index); threads auto-created by signal on group/trip creation
- [x] `ws/chat/{thread_id}/` consumer (reuses `JWTAuthMiddleware`, connect-time participant check, `message.send`/`message.read` → `message.new`/`message.read`)
- [x] REST: `/chat-threads/` list (scoped), `/chat-threads/{id}/messages/` cursor-paginated history + POST send, `/chat-threads/{id}/read/` mark-read-up-to
- [x] Tests: consumer auth rejection (4001/4003) + fan-out, thread scoping, send/history, read-receipt idempotency (20 tests)

## Stage 7 — Notifications ✅
- [x] Models: `Notification` (+ `delivered_at`/`dedupe_key`, see DECISIONS), `NotificationPreference`, `DeviceToken`
- [x] Poller beat (`poll_upcoming_dismissals`, every 5 min) → per-child `send_dismissal_reminder` (dedupe-keyed, idempotent)
- [x] Expo push fan-out task (`send_push_notification`, `delivered_at` guard, `PUSH_BACKEND=fake|expo`, per-type push preference)
- [x] `ws/notifications/{user_id}/` consumer (own-stream-only auth, read-only, `notification.new`) + post_save fan-out signal
- [x] REST: `/notifications/` (`?is_read=`) + `/{id}/read/`, `/notification-preferences/` list + PATCH by type, `/device-tokens/` register/delete
- [x] Triggers wired: swap request, chat message, schedule change, driver arrived (stop → arrived), pickup cascade (PickupEvent → picked_up)
- [x] Tests: API scoping, consumer auth rejection (4001/4003) + fan-out, push idempotency/preference gating, dismissal dedupe, poller window, all four triggers (26 tests)

## Stage 8 — Safety ✅
- [x] `SOSAlert` model (in the `trips` app; `(status, created_at)` index) + `/sos-alerts/` raise/list, `/{id}/resolve/`
- [x] Immediate fan-out (`trips.sos.fan_out_sos`) bypassing the deferred push queue: `type=sos` Notification per guardian pushed to Expo synchronously in-request (`delivered_at` makes the queued dup a no-op)
- [x] Dual delivery: per-guardian `notification.new` (via the notification signal) + `sos_alert` on the trip's `trip_{id}` channel (new `TripConsumer.sos_alert` handler) + push
- [x] Recipients = trip guardians (driver + stop-child families + group members) minus the raiser (`notifications.recipients.trip_recipients`)
- [x] Tests: guardian fan-out (raiser/outsider excluded), immediate push + `delivered_at`, WS broadcast to trip channel, list scoping, resolve, raise/resolve authorization (7 tests)

## Stage 9 — Media, polish, deploy
- [ ] Cloudinary integration
- [ ] OpenAPI schema export (`schema/openapi.yaml`)
- [ ] DigitalOcean App Platform deploy
