# API Design — School Pickup Coordinator

## Conventions

- Base path: `/api/v1/`
- Auth: `Authorization: Bearer <clerk_session_jwt>` on every request. A custom DRF authentication class validates against Clerk's JWKS endpoint and JIT-provisions/updates the local `User` row as a fallback; the `/webhooks/clerk/` endpoint below is the primary sync path for profile data.
- Pagination: `PageNumberPagination` (default `page_size=20`) for most list endpoints; `CursorPagination` ordered by `created_at` for `chat_messages` and `location_pings` history (time-ordered, append-heavy data).
- Error envelope:
```json
{
  "error": {
    "code": "not_found",
    "message": "Carpool group not found",
    "details": {}
  }
}
```
- Permissions are scoped through membership: you can only touch a `Family`'s data if you're a `family_member`; you can only touch a `CarpoolGroup`'s data if your family is a `carpool_group_member`.

---

## Auth & Users

| Method | Path | Description |
|---|---|---|
| GET | `/me/` | Current user profile (JIT-created on first call if new) |
| PATCH | `/me/` | Update name/avatar |
| POST | `/device-tokens/` | Register push token |
| DELETE | `/device-tokens/{id}/` | Remove push token (logout) |
| POST | `/webhooks/clerk/` | Clerk webhook receiver (`user.created`, `user.updated`, `user.deleted`) — authenticated via Svix signature verification, not a user JWT |

## Families

| Method | Path | Description |
|---|---|---|
| GET | `/families/` | Families the user belongs to |
| POST | `/families/` | Create a family (creator becomes owner) |
| GET | `/families/{id}/` | Detail |
| PATCH | `/families/{id}/` | Update name (owner only) |
| GET | `/families/{id}/members/` | List members |
| POST | `/families/{id}/members/invite/` | Invite by email (creates pending invite) |
| DELETE | `/families/{id}/members/{member_id}/` | Remove member (owner only) |

## Children

| Method | Path | Description |
|---|---|---|
| GET | `/children/` | List children across the user's families (filter: `?family=`, `?school=`) |
| POST | `/children/` | Create |
| GET | `/children/{id}/` | Detail |
| PATCH | `/children/{id}/` | Update |
| DELETE | `/children/{id}/` | Soft-delete |
| POST | `/children/{id}/photo/` | Upload avatar (proxies to Cloudinary, stores returned URL) |

## Schools

| Method | Path | Description |
|---|---|---|
| GET | `/schools/` | List/search (`?search=name`) — shared reference data, not family-scoped |
| POST | `/schools/` | Create (any authenticated user can add a school not yet in the system) |
| GET | `/schools/{id}/` | Detail |
| PATCH | `/schools/{id}/` | Update |
| GET | `/schools/{id}/calendar-exceptions/` | List exceptions (`?from=&to=`) |
| POST | `/schools/{id}/calendar-exceptions/` | Add exception |

## Activities

| Method | Path | Description |
|---|---|---|
| GET | `/children/{child_id}/activities/` | List |
| POST | `/children/{child_id}/activities/` | Create |
| PATCH | `/activities/{id}/` | Update |
| DELETE | `/activities/{id}/` | Delete |

## Carpool Groups

| Method | Path | Description |
|---|---|---|
| GET | `/carpool-groups/` | Groups the user's families belong to |
| POST | `/carpool-groups/` | Create (scoped to a school) |
| GET | `/carpool-groups/{id}/` | Detail |
| POST | `/carpool-groups/join/` | Join via invite code |
| GET | `/carpool-groups/{id}/members/` | List member families |
| DELETE | `/carpool-groups/{id}/members/{member_id}/` | Remove (admin only) |

## Rotation & Assignments

| Method | Path | Description |
|---|---|---|
| GET | `/carpool-groups/{id}/rotation-rule/` | Current rule |
| PUT | `/carpool-groups/{id}/rotation-rule/` | Create/replace rule + order (admin only) |
| GET | `/carpool-groups/{id}/assignments/` | List (`?from=&to=`) |
| POST | `/carpool-groups/{id}/assignments/generate/` | Run the auto-suggestion engine for a date range → creates `suggested` assignments |
| PATCH | `/assignments/{id}/` | Manually edit (reassign driver, add notes) |
| POST | `/assignments/{id}/confirm/` | Driver family confirms a suggested assignment |
| POST | `/assignments/{id}/swap-requests/` | Request a swap |
| POST | `/swap-requests/{id}/respond/` | Accept/reject (`{"action": "accept"}`) |

## Trips (live tracking)

| Method | Path | Description |
|---|---|---|
| GET | `/trips/` | List (`?date=&carpool_group=`) |
| POST | `/trips/` | Create for today's assignment/pickup, with stops |
| GET | `/trips/{id}/` | Detail incl. stops and current status |
| POST | `/trips/{id}/start/` | Driver starts the trip |
| POST | `/trips/{id}/end/` | Driver ends the trip |
| PATCH | `/trips/{id}/stops/{stop_id}/` | Update stop status (`arrived`, `picked_up`, `skipped`) |
| POST | `/trips/{id}/location/` | Fallback REST ping (primary path is the WebSocket below; this exists for spotty-connectivity retries) |
| GET | `/trips/{id}/location/latest/` | Last known location (for a parent opening the app mid-trip) |

## Pickup Events

| Method | Path | Description |
|---|---|---|
| GET | `/pickup-events/` | "Today" view (`?date=&family=`) — one row per child |
| PATCH | `/pickup-events/{id}/` | Manual status/method override |

## Chat

| Method | Path | Description |
|---|---|---|
| GET | `/chat-threads/` | List threads user has access to |
| GET | `/chat-threads/{id}/messages/` | Paginated history (cursor) |
| POST | `/chat-threads/{id}/messages/` | Send (REST fallback; primary path is WebSocket) |
| POST | `/chat-threads/{id}/read/` | Mark thread read up to a message id |

## Notifications

| Method | Path | Description |
|---|---|---|
| GET | `/notifications/` | List (`?is_read=false`) |
| POST | `/notifications/{id}/read/` | Mark read |
| GET | `/notification-preferences/` | List |
| PATCH | `/notification-preferences/{type}/` | Update channel toggles |

## SOS

| Method | Path | Description |
|---|---|---|
| POST | `/sos-alerts/` | Raise (from an active trip) — fans out to all guardians tied to that trip/group immediately |
| GET | `/sos-alerts/` | Active alerts visible to the user |
| POST | `/sos-alerts/{id}/resolve/` | Resolve |

---

## WebSocket Channels (Django Channels)

| Path | Purpose | Events |
|---|---|---|
| `ws/trips/{trip_id}/` | Live tracking room for one trip | `location_update`, `stop_status_update`, `trip_status_update` |
| `ws/chat/{thread_id}/` | Chat room | `message.new`, `message.read` |
| `ws/notifications/{user_id}/` | In-app push while app is foregrounded (background delivery still goes through Expo push/FCM/APNs) | `notification.new` |

**Auth on WS connect**: pass the Clerk session JWT as a query param or first-message payload; the consumer validates it the same way the REST authentication class does, then checks room membership before accepting.

### Sample: `location_update` event (driver → server → all trip watchers)
```json
{
  "type": "location_update",
  "trip_id": "b3f1...",
  "lat": 41.8781,
  "lng": -87.6298,
  "speed": 8.2,
  "heading": 134.0,
  "recorded_at": "2026-07-06T14:32:10Z"
}
```

### Sample: `stop_status_update` event
```json
{
  "type": "stop_status_update",
  "trip_id": "b3f1...",
  "stop_id": "9a2c...",
  "status": "arrived",
  "eta": null
}
```

---

## Celery Tasks

| Task | Trigger | Purpose |
|---|---|---|
| `send_dismissal_reminder` | Celery beat, per school's dismissal time minus N minutes | Push reminder to whoever's responsible that day |
| `generate_carpool_suggestions` | On-demand (from the `/generate/` endpoint) or nightly beat for the coming week | Runs the rotation algorithm, writes `suggested` `CarpoolAssignment` rows |
| `recalculate_trip_eta` | On each location ping (throttled, e.g. max once per 30s per trip) | Calls Google Distance Matrix, updates `TripStop.eta` |
| `send_push_notification` | Called by signals/other tasks | Fans out to Expo push service using stored `DeviceToken`s |
| `expire_stale_swap_requests` | Celery beat, hourly | Auto-expire swap requests left unanswered too long |
| `cleanup_old_location_pings` | Celery beat, nightly | Deletes `LocationPing` rows older than the retention window |

### Sample: rotation generation response
```json
POST /carpool-groups/{id}/assignments/generate/
{
  "from": "2026-07-13",
  "to": "2026-07-17"
}

→ 201
{
  "created": [
    {
      "id": "...",
      "date": "2026-07-13",
      "driver_family": "The Ortiz Family",
      "status": "suggested",
      "is_auto_suggested": true
    }
  ]
}
```

### Sample: pickup event status update
```json
PATCH /pickup-events/{id}/
{
  "status": "picked_up"
}

→ 200
{
  "id": "...",
  "child": "Mia Ortiz",
  "date": "2026-07-06",
  "status": "picked_up",
  "pickup_method": "carpool"
}
```
