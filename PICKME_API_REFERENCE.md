# PickMe — School Pickup Coordinator API Reference

This is the API contract for the **PickMe backend** — a Django 5 / DRF service
(Postgres + Redis + Django Channels + Celery) that backs the **React Native
(Expo) frontend** you are building in a separate codebase, following
`instructions/FRONTEND-ARCHITECTURE.md`.

**This doc reflects the real, running, tested implementation** (stages 0–8:
auth, families, schools, activities, carpool + rotation engine, trips + live
tracking, pickup events, chat, notifications, SOS). Where it differs from the
older planning docs in `instructions/`, this doc wins. Read it end-to-end once;
it is the source of truth for exact routes, field names, response shapes,
WebSocket events, and the business rules the shapes don't explain.

- **Stack the frontend targets:** Expo Router · React Native Reusables +
  NativeWind · TanStack Query v5 (all REST) · Zustand (ephemeral) · native
  `WebSocket` · `@clerk/clerk-expo` (auth) · `openapi-fetch` (typed client) ·
  `expo-notifications` (push).
- **Base REST URL:** `http://localhost:8000/api/v1` in local dev (the ASGI
  server runs on `:8000`). Every REST path below is relative to `/api/v1`.
- **Base WebSocket URL:** `ws://localhost:8000` (paths are `/ws/...`, **not**
  under `/api/v1`).
- **IDs are UUID strings** everywhere except `LocationPing.id` (a big integer —
  it's high-volume). **All timestamps are UTC ISO-8601** (`2026-07-07T14:32:10Z`).
  School-local times are resolved server-side from `School.timezone` (IANA).

---

## 1. Auth — Clerk

Authentication is **Clerk**, not a backend-owned email/password system. There is
**no `/login`, `/register`, or `/logout` on this backend** — Clerk hosts all of
that. The frontend uses `@clerk/clerk-expo`'s prebuilt flows; the backend only
*verifies* the Clerk-issued session JWT and mirrors the user locally.

### How a request is authenticated

Send the Clerk **session JWT** as a Bearer token on every request:

```
Authorization: Bearer <clerk session jwt>
```

In Expo, get the token from Clerk and feed it to your API client:

```ts
import { useAuth } from "@clerk/clerk-expo";
const { getToken } = useAuth();
const token = await getToken();            // refreshes automatically
// openapi-fetch middleware: headers.set("Authorization", `Bearer ${token}`)
```

The backend verifies the JWT's RS256 signature against Clerk's JWKS (cached),
checks `iss`/`exp`/`iat`, and then **JIT-provisions a local `User` row** keyed by
the token's `sub` (Clerk user id) on first contact. So a brand-new Clerk user is
usable immediately; their profile (name/email/avatar) is filled in by a Clerk
**webhook** (`POST /api/v1/webhooks/clerk/`, Svix-verified — backend-internal,
not something the frontend calls) on `user.created`/`updated`/`deleted`.

**Auth failures** return `401` with the standard error envelope (§3). A missing
or malformed `Authorization` header, an expired token, or an inactive user all
land here.

### WebSocket auth

WebSockets can't send an `Authorization` header from the browser/RN `WebSocket`
API, so the token goes in the **query string** as `?token=<jwt>`:

```
ws://localhost:8000/ws/trips/<tripId>/?token=<clerk session jwt>
```

The server verifies it the same way as REST, sets the connection's user, then
each consumer checks room membership before accepting. On a bad/absent token the
socket is **closed with code `4001`** (unauthenticated); on a valid token that
isn't allowed in that room, **`4003`** (forbidden). See §9.

### ⚠️ There is no `/me` endpoint yet (open item)

The backend does not currently expose "who am I" returning the **local `User`
UUID**. You get the Clerk identity from `@clerk/clerk-expo` directly, but a few
things need the *local* UUID:

- connecting to `ws/notifications/{user_id}/` (the path is the local UUID),
- rendering chat "mine vs theirs" (`ChatMessage.sender` is the local UUID),
- checking "am I the driver / the raiser" (`Trip.driver`, `SOSAlert.raised_by`).

**Flag this back to the backend** — it's a ~10-line addition
(`GET /api/v1/me/` → the `User` summary). Until then, most screens work off
already-scoped list endpoints and don't need the raw UUID; the notification
socket is the one hard blocker. (Ask and it'll be added.)

---

## 2. Permission & scoping model

Every resource is **membership-scoped server-side** — the UI never has to filter
for privacy, and it can't bypass it. Three scopes:

| Scope | Rule | Used by |
|---|---|---|
| **Family** | You must be a `FamilyMember` of the family that owns the object | families, children, activities, pickup events |
| **Carpool group** | One of *your* families must be a member of the group | groups, rotation rules, assignments, swap requests |
| **Trip** | You're the trip's driver, OR in a family with a child at one of its stops, OR a member of its carpool group | trips, stops, location, chat, SOS |

**What you get when you're not allowed:**

- **List endpoints** simply omit rows you can't see (scoped querysets) — you
  never see family B's children, full stop.
- **Detail / action endpoints** return **`404`** when the object isn't in your
  scope (it "doesn't exist" for you), and **`403`** when you're in scope but lack
  the specific role (e.g. a non-owner editing a family, a non-admin editing a
  rotation rule, a non-driver sending trip events).

Some notable role gates:
- **Family owner** only: rename family, remove a member.
- **Carpool group admin** only: edit rotation rule, remove a member.
- **Assigned driver family** only: confirm an assignment, request a swap.
- **Swap target family** only: respond to a swap.
- **Trip driver** only: start/end trip, update stop status, send location.

`School` is **shared reference data** — any authenticated user can list, create,
and edit schools and their calendar exceptions (they're not family-owned).

---

## 3. Conventions

### Error envelope

Every 4xx/5xx from the API has this exact shape:

```json
{ "error": { "code": "validation_error", "message": "Invalid input.", "details": { "email": ["Enter a valid email address."] } } }
```

- `code` — machine string: `authentication_failed`, `not_authenticated`,
  `permission_denied`, `not_found`, `validation_error`, `parse_error`, etc.
- `message` — a human string safe to surface (or map to your own copy).
- `details` — for `validation_error`, a `{ field: [messages] }` map (non-field
  errors under `non_field_errors`); `{}` otherwise.

Your `openapi-fetch` error handler should read `error.error.message` for toasts
and `error.error.details` for inline field errors.

### Pagination

Two styles:

- **Page-number (default, everything except chat history).** Query with
  `?page=<n>&page_size=<n>` (`page_size` max 100, default 20). Response:
  ```json
  { "count": 42, "next": "http://.../?page=3", "previous": "http://.../?page=1", "results": [ ... ] }
  ```
- **Cursor (chat message history only).** Opaque cursor tokens, newest-first.
  Response:
  ```json
  { "next": "http://...?cursor=cD0y", "previous": null, "results": [ ... ] }
  ```
  Use TanStack Query's `useInfiniteQuery`; `getNextPageParam` = pull the `cursor`
  param out of `next` (or just fetch `next` verbatim).

### Dates & times

- **Datetimes**: UTC ISO-8601, e.g. `"2026-07-07T15:00:00Z"`.
- **Dates**: `"YYYY-MM-DD"` (e.g. a trip/assignment `date`).
- **Times**: `"HH:MM"` / `"HH:MM:SS"` (e.g. `School.default_dismissal_time`,
  `Activity.start_time`).
- **Weekdays are Python convention: `0 = Monday … 6 = Sunday`** (used by
  `Activity.day_of_week`, `School.early_dismissal_days` keys, and rotation
  `cycle_days`). Don't assume Sunday=0.

---

## 4. Data types (as the API returns them)

Relations are returned as **bare UUID strings** unless noted as nested. A
`*_name` companion field is included on several resources so you don't need a
second fetch just to render a label.

### User (summary — how a user appears when nested)
```ts
{ id, full_name, email, avatar_url }
```

### Family
```ts
{ id, name, created_by /* User id */, created_at, member_count /* on list/retrieve */ }
```

### FamilyMember
```ts
{ id, user: { id, full_name, email, avatar_url }, role: "owner" | "member", joined_at }
```

### FamilyInvite
```ts
{ id, family, email, status: "pending" | "accepted" | "revoked", created_at }
```

### School  (shared reference data)
```ts
{
  id, name, address,
  lat, lng,                      // decimal strings or null
  timezone,                      // IANA, e.g. "America/Chicago"
  default_dismissal_time,        // "15:00:00"
  early_dismissal_days,          // { "2": "13:30" } → every Wednesday 1:30pm, keys 0=Mon; or null
  phone, created_at
}
```

### SchoolCalendarException
```ts
{ id, school, date, dismissal_time /* null = NO SCHOOL that day */, reason, created_at }
```

### Child
```ts
{
  id, family, school /* id or null */, full_name,
  date_of_birth /* "YYYY-MM-DD" | null */, grade /* string | null */,
  photo_url /* Cloudinary URL | null */, color_tag /* e.g. "#4F86C6" | null */,
  notes, created_at
}
```
Deleting a child is a **soft delete** (it stops appearing in lists but pickup
history keeps referencing it).

### Activity  (recurring after-school activity)
```ts
{
  id, child, name,
  day_of_week: 0-6,              // 0 = Monday
  start_time, end_time,          // "HH:MM:SS"; end must be after start
  location_name, location_lat, location_lng,
  created_at
}
```

### CarpoolGroup
```ts
{ id, school, name, invite_code /* e.g. "K7MNP2QR" */, created_by, created_at }
```
On **create**, the body also needs a write-only `family` (one of *your*
families) — it becomes the group's first admin member. `invite_code` is
server-generated; share it for others to join.

### CarpoolGroupMember
```ts
{ id, family, family_name, role: "admin" | "member", joined_at }
```

### CarpoolRotationRule  (one per group)
```ts
{
  id,
  rotation_type: "round_robin" | "weighted" | "manual_only",
  cycle_days: number[],          // weekdays the rotation covers, 0=Mon, e.g. [0,1,2,3,4]
  start_date,                    // anchor for the rotation order
  order: [ { family, family_name, position: 0-based, weight /* turns per cycle, weighted type */ } ],
  created_at, updated_at
}
```

### CarpoolAssignment  (one per group per date)
```ts
{
  id, carpool_group, date,
  driver_family, driver_family_name,
  driver_user /* id | null — set once a specific parent confirms */,
  status: "suggested" | "confirmed" | "swap_pending" | "completed" | "cancelled",
  is_auto_suggested, notes, created_at, updated_at
}
```

### CarpoolSwapRequest
```ts
{
  id, assignment, requested_by /* User id */,
  target_family, target_family_name,
  status: "pending" | "accepted" | "rejected" | "expired",
  reason, created_at, resolved_at
}
```

### Trip
```ts
{
  id, driver /* User id */, driver_name,
  carpool_group /* id | null — null = solo parent pickup */,
  date,
  status: "not_started" | "in_progress" | "completed" | "cancelled",
  started_at, ended_at,
  tracking_mode: "live_gps" | "status_only",
  created_at,
  stops: TripStop[]
}
```

### TripStop
```ts
{
  id, school /* id | null */, activity /* id | null */, sequence_order,
  eta /* ISO datetime | null — recomputed from live pings */,
  status: "pending" | "en_route" | "arrived" | "picked_up" | "skipped",
  actual_arrival_time /* ISO | null */,
  children: [ { id, child, child_name, picked_up_at /* ISO | null */ } ]
}
```

### LocationPing
```ts
{ id /* integer */, lat, lng, speed /* m/s | null */, heading /* degrees | null */, recorded_at }
```

### PickupEvent  ("Today" row — one per child per date)
```ts
{
  id, child, child_name, date,
  pickup_method: "parent" | "carpool" | "aftercare" | "bus" | "walker",
  carpool_assignment /* id | null */, trip_stop_child /* id | null — links to live tracking */,
  status: "scheduled" | "en_route" | "arrived" | "picked_up" | "missed" | "cancelled",
  scheduled_time /* resolved dismissal/activity-end datetime, UTC | null */,
  created_at
}
```

### ChatThread
```ts
{ id, context_type: "carpool_group" | "trip", carpool_group /* id | null */, trip /* id | null */, created_at }
```
Threads are **auto-created** (one per group, one per trip) — there is no
create-thread endpoint.

### ChatMessage
```ts
{
  id, thread, sender /* User id */, sender_name,
  content /* string | null */, attachment_url /* Cloudinary | null */,
  message_type: "text" | "image" | "system",
  created_at
}
```

### Notification
```ts
{
  id,
  type: "pickup_reminder" | "driver_arrived" | "swap_request" | "chat_message" | "schedule_change" | "sos",
  title, body,
  data /* deep-link payload, shape varies by type — see §8 */,
  is_read, created_at
}
```

### NotificationPreference
```ts
{ id, notification_type, push_enabled, sms_enabled, email_enabled }
```
`GET` returns **one row per type** (defaults for any you haven't customized).
SMS/email are modeled but not yet delivered — only `push_enabled` currently has
an effect.

### DeviceToken
```ts
{ id, token /* Expo push token */, platform: "ios" | "android", created_at }
```

### SOSAlert
```ts
{
  id, trip /* id */, raised_by /* User id */,
  lat, lng, message,
  status: "active" | "resolved",
  created_at, resolved_at, resolved_by /* User id | null */
}
```

---

## 5. Endpoints — Families, Children, Schools

### Health (public, no auth)
```
GET /health/ → { "status": "ok" }
```

### Families
```
GET    /families/                         # families you're a member of
POST   /families/            { "name": "The Okonkwos" }   # you become owner
GET    /families/{id}/
PATCH  /families/{id}/        { "name": "..." }           # owner only → 403 otherwise
GET    /families/{id}/members/            # paginated FamilyMember[]
POST   /families/{id}/members/invite   { "email": "co-parent@example.com" }
         → 201 FamilyInvite   # emails a redeem token (console backend in dev)
DELETE /families/{id}/members/{memberId}/  # owner only; can't remove the owner
```

### Accept a family invite
```
POST /family-invites/accept/   { "token": "<uuid from the invite email>" }
→ 200/201 { "family": Family, "member": FamilyMember }
```
Call this as the **invited (signed-in) user** — it adds *you* to the family.

### Children
```
GET    /children/                         # active children across your families
        ?family=<id>&school=<id>          # optional filters
POST   /children/   { "family": "<id>", "school": "<id>", "full_name": "Ada", "grade": "3", "color_tag": "#4F86C6", "photo_url": "..." }
GET    /children/{id}/
PATCH  /children/{id}/   { ...any field... }
DELETE /children/{id}/                     # soft delete (204)
```
`family` must be one you belong to (else `400`).

### Activities (per child)
```
GET  /children/{childId}/activities/       # paginated, ordered by weekday+time
POST /children/{childId}/activities/
       { "name": "Soccer", "day_of_week": 2, "start_time": "15:30", "end_time": "17:00",
         "location_name": "Field 4", "location_lat": 41.9, "location_lng": -87.6 }
PATCH  /activities/{id}/    { ...any field... }
DELETE /activities/{id}/                    # 204
GET    /activities/{id}/
```

### Schools (shared reference data — any authed user)
```
GET    /schools/            ?search=lincoln     # search name/address
POST   /schools/   { "name": "...", "address": "...", "timezone": "America/Chicago",
                     "default_dismissal_time": "15:00", "lat": 41.9, "lng": -87.6,
                     "early_dismissal_days": { "2": "13:30" }, "phone": "..." }
GET    /schools/{id}/
PATCH  /schools/{id}/
```
`timezone` must be a valid IANA name; `early_dismissal_days` keys are `"0"`–`"6"`
(0=Mon), values `"HH:MM"`.

### School calendar exceptions
```
GET  /schools/{id}/calendar-exceptions/     ?from=2026-09-01&to=2026-12-31
POST /schools/{id}/calendar-exceptions/
       { "date": "2026-11-26", "dismissal_time": null, "reason": "Thanksgiving break" }
       # dismissal_time: null = no school that day; a time = early/late override
```
One exception per (school, date) — a duplicate date `400`s. Editing an exception
fires a `schedule_change` notification to families with a child at that school
(§8).

---

## 6. Endpoints — Carpool & rotation

### Groups
```
GET  /carpool-groups/                       # groups any of your families belong to
POST /carpool-groups/   { "school": "<id>", "name": "Morning Crew", "family": "<your family id>" }
GET  /carpool-groups/{id}/
GET  /carpool-groups/{id}/members/          # paginated CarpoolGroupMember[]
DELETE /carpool-groups/{id}/members/{memberId}/   # admin only; can't remove the last admin
```

### Join by invite code
```
POST /carpool-groups/join/   { "invite_code": "K7MNP2QR", "family": "<your family id>" }
→ 200/201 { "group": CarpoolGroup, "member": CarpoolGroupMember }
```

### Rotation rule (admin to edit)
```
GET /carpool-groups/{id}/rotation-rule/     → RotationRule (404 if none configured)
PUT /carpool-groups/{id}/rotation-rule/     # admin only
  {
    "rotation_type": "weighted",
    "cycle_days": [0,1,2,3,4],
    "start_date": "2026-09-01",
    "order": [
      { "family": "<famA>", "position": 0, "weight": 2 },
      { "family": "<famB>", "position": 1, "weight": 1 }
    ]
  }
  → RotationRule
```
Every `order` family must be a group member; positions must be unique;
`manual_only` may omit `order`.

### Assignments (the rotation calendar)
```
GET  /carpool-groups/{id}/assignments/      ?from=2026-09-01&to=2026-09-30
       → paginated CarpoolAssignment[]  (ordered by date)
POST /carpool-groups/{id}/assignments/generate/   { "from": "2026-09-01", "to": "2026-09-30" }
       → 201 { "created": CarpoolAssignment[] }
```
`generate` runs the rotation engine over the range and writes `suggested`
assignments — it **never overwrites** a date that already has an assignment
(manual entries and confirmations are preserved). See §8 for the algorithm.

### Confirm / swap (on the assignment)
```
POST /assignments/{id}/confirm/             # driver family only → status "confirmed", sets driver_user = you
PATCH /assignments/{id}/   { "driver_family": "<id>", "driver_user": "<id>", "notes": "..." }   # manual override
POST /assignments/{id}/swap-requests/   { "target_family": "<id>", "reason": "away that day" }
       # driver family only; → 201 SwapRequest, assignment goes "swap_pending"
```

### Swap requests
```
GET  /swap-requests/                        # swaps visible to your groups
POST /swap-requests/{id}/respond/   { "action": "accept" | "reject" }
       # target family only
       → { "swap_request": SwapRequest, "assignment": CarpoolAssignment }
```
Accepting reassigns just that one date to the target family (`confirmed`);
rejecting reverts the assignment. Pending swaps auto-expire after
`SWAP_REQUEST_EXPIRY_HOURS` (48h) via a beat task. Creating a swap fires a
`swap_request` notification to the target family (§8).

---

## 7. Endpoints — Trips, tracking, pickups

### Trips
```
GET  /trips/          ?date=2026-09-14&carpool_group=<id>    # trips you're party to
POST /trips/
  {
    "carpool_group": "<id | null>",
    "date": "2026-09-14",
    "tracking_mode": "live_gps",
    "stops": [
      { "school": "<id>", "sequence_order": 1, "children": ["<childId>", "<childId>"] },
      { "activity": "<id>", "sequence_order": 2, "children": ["<childId>"] }
    ]
  }
  → 201 Trip   # the creator is the driver
GET  /trips/{id}/       → Trip (with nested stops + children)
```
Every child on a stop must be visible to you (your family or a shared carpool
group), else `400`. A stop needs a `school` **or** an `activity`.

### Trip lifecycle (driver only)
```
POST  /trips/{id}/start/     → Trip   # not_started → in_progress; pending stops → en_route
POST  /trips/{id}/end/       → Trip   # in_progress → completed
PATCH /trips/{id}/stops/{stopId}/
        { "status": "arrived" }                      # en_route → arrived
        { "status": "picked_up" }                    # arrived → picked_up (all children)
        { "status": "picked_up", "children": ["<childId>"] }   # subset
        { "status": "skipped" }
        → TripStop
```
Valid transitions: `pending → en_route|skipped`, `en_route → arrived|skipped`,
`arrived → picked_up`. Marking a stop `arrived` fires a `driver_arrived`
notification; marking children `picked_up` cascades to their `PickupEvent`
(→ `picked_up`) and fires a per-family notification (§8).

### Location (driver posts; anyone party reads) — REST fallback
The **primary** path for live location is the WebSocket (§9); these REST routes
exist for spotty-connectivity retries and initial hydration.
```
POST /trips/{id}/location/   { "lat": 41.878, "lng": -87.63, "speed": 8.2, "heading": 134, "recorded_at": "2026-09-14T14:32:10Z" }
       → 201 LocationPing    # driver only; trip must be in_progress
GET  /trips/{id}/location/latest/   → LocationPing (404 if none yet)
```

### Pickup events — the "Today" screen
```
GET   /pickup-events/     ?date=2026-09-14&family=<id>    # defaults to today
        → paginated PickupEvent[]   # one row per child across all your families' schools
GET   /pickup-events/{id}/
PATCH /pickup-events/{id}/   { "status": "picked_up", "pickup_method": "parent" }   # manual override
```
Rows are generated automatically (a nightly beat + trip-start cascade), so the
"Today" screen is a straight read. Live trip updates flow into these rows via
signals, so re-fetching (or WS-invalidating) reflects `en_route`/`arrived`/
`picked_up` as a driver progresses.

---

## 8. Endpoints — Chat, Notifications, SOS

### Chat
```
GET  /chat-threads/                          # group + trip threads you can access
GET  /chat-threads/{id}/messages/            # cursor-paginated history, newest first
POST /chat-threads/{id}/messages/   { "content": "running 5 late", "attachment_url": "...", "message_type": "text" }
       → 201 ChatMessage           # REST fallback; primary send path is the WebSocket
POST /chat-threads/{id}/read/   { "message_id": "<id>" }   # mark read up to & including this message
       → { "marked_read": <count> }
```
A message needs `content` or `attachment_url`. Sending (via REST or WS) fires a
`chat_message` notification to every other participant (§9 for the live path).

### Notifications
```
GET  /notifications/          ?is_read=false        # your notifications, newest first
POST /notifications/{id}/read/     → Notification    # marks read
```

### Notification preferences
```
GET   /notification-preferences/             # one row per type (materialized defaults)
PATCH /notification-preferences/{type}/   { "push_enabled": false }
        # {type} ∈ pickup_reminder | driver_arrived | swap_request | chat_message | schedule_change | sos
```

### Device tokens (push registration)
```
POST   /device-tokens/   { "token": "ExponentPushToken[xxx]", "platform": "ios" }   # idempotent; re-register rebinds
DELETE /device-tokens/{id}/                  # on logout
```
Register the Expo push token right after permission is granted; delete on
sign-out. Push only actually sends when the backend runs with `PUSH_BACKEND=expo`
(dev default is `fake`, which no-ops).

### Media (Cloudinary)
```
POST /children/{id}/photo/     # multipart file field "file" → uploads, stores, returns Child
        # or JSON { "photo_url": "https://res.cloudinary.com/..." } for an already-hosted image
POST /media/signature/   { "folder": "chat", "resource_type": "image" }
        → { cloud_name, api_key, timestamp, folder, signature, resource_type, upload_url }
```
`/media/signature/` gives you short-lived signed params to upload **directly**
from the app to Cloudinary (the API secret never leaves the server) — use it for
chat attachments: POST the file to `upload_url` with those fields, get back a
`secure_url`, then send the message with `attachment_url` set. For avatars you
can either use the same direct flow then `PATCH`/`POST .../photo/ {photo_url}`,
or just POST the raw file to `/children/{id}/photo/` and let the backend proxy it.

### SOS
```
POST /sos-alerts/   { "trip": "<id>", "lat": 41.878, "lng": -87.63, "message": "flat tire, kids safe" }
       → 201 SOSAlert    # you must be a participant on that trip
GET  /sos-alerts/          ?status=active            # active alerts on trips you can see (or that you raised)
POST /sos-alerts/{id}/resolve/     → SOSAlert        # any guardian on the trip can resolve
```
Raising an SOS **fans out immediately** to every guardian on the trip (minus you)
over three channels at once: a `type=sos` push, a per-user `notification.new`,
and an `sos_alert` event on the trip's live channel (§9). This deliberately
bypasses the normal deferred push queue — build the receiving UI (screen 18,
`SOSBanner`) to react to any of the three.

### Notification `data` payloads (for deep-linking on tap)

| `type` | `data` shape | Suggested deep link |
|---|---|---|
| `pickup_reminder` | `{ child_id, date }` | Today |
| `driver_arrived` | `{ trip_id, stop_id }` *(arrival)* or `{ child_id, pickup_event_id, date }` *(picked up)* | Live Trip / Today |
| `swap_request` | `{ swap_request_id, assignment_id, carpool_group_id, date }` | Swap respond `swap/[requestId]` |
| `chat_message` | `{ thread_id, message_id }` | Conversation `chat/[threadId]` |
| `schedule_change` | `{ school_id, date }` | School detail |
| `sos` | `{ sos_alert_id, trip_id, lat, lng }` | SOS takeover |

---

## 9. WebSocket channels (Django Channels)

Connect with the Clerk JWT in the query string. On success the socket is open;
on failure it closes with **`4001`** (bad/missing token) or **`4003`** (valid
token, not allowed in this room). Events are JSON. Note the **two naming styles**
that coexist by design: trip events use `snake_case` (`location_update`), chat &
notifications use `dotted` names (`message.new`, `notification.new`).

The golden rule from `FRONTEND-ARCHITECTURE.md`: **socket hooks write incoming
events into the TanStack Query cache and hold no state of their own.**

### `ws/trips/{tripId}/` — live tracking

```
ws://localhost:8000/ws/trips/<tripId>/?token=<jwt>
```
Authorized for the driver, families with a child at a stop, and group members.

**Client → server** (driver only; others get an `error` frame):
```json
{ "type": "location_update", "lat": 41.878, "lng": -87.63, "speed": 8.2, "heading": 134, "recorded_at": "2026-09-14T14:32:10Z" }
{ "type": "stop_status_update", "stop_id": "<id>", "status": "arrived" }
```

**Server → all watchers:**
```json
{ "type": "location_update", "trip_id": "<id>", "lat": "41.878", "lng": "-87.63", "speed": 8.2, "heading": 134, "recorded_at": "..." }
{ "type": "stop_status_update", "trip_id": "<id>", "stop_id": "<id>", "status": "arrived", "eta": null }
{ "type": "trip_status_update", "trip_id": "<id>", "status": "in_progress", "stop_id": "<id>", "eta": "..." }
{ "type": "sos_alert", "sos": { id, trip_id, raised_by, lat, lng, message, status, created_at } }
```
Cache wiring: `location_update` → `setQueryData(['trip', id, 'latest-location'])`;
`stop_status_update`/`trip_status_update` → patch `['trip', id]`; `sos_alert` →
trigger the SOS takeover.

### `ws/chat/{threadId}/` — conversation

```
ws://localhost:8000/ws/chat/<threadId>/?token=<jwt>
```
Authorized for group members / trip participants of the thread.

**Client → server:**
```json
{ "type": "message.send", "content": "on my way", "attachment_url": null, "message_type": "text" }
{ "type": "message.read", "message_id": "<id>" }
```
**Server → all participants:**
```json
{ "type": "message.new", "message": { id, thread, sender, sender_name, content, attachment_url, message_type, created_at } }
{ "type": "message.read", "thread": "<id>", "user": "<id>", "up_to_message": "<id>", "count": 3 }
```
Cache wiring: `message.new` → append to the `['messages', threadId]` infinite
query and invalidate `['threads']`.

### `ws/notifications/{userId}/` — personal push stream

```
ws://localhost:8000/ws/notifications/<localUserId>/?token=<jwt>
```
**Own stream only** — `{userId}` must equal your local `User` UUID or the socket
`4003`s. Read-only (any frame you send gets an `error` back). This is the
in-app/foreground delivery; background delivery is Expo push.
```json
{ "type": "notification.new", "notification": { id, type, title, body, data, is_read, created_at } }
```
Cache wiring: prepend to `['notifications']` and bump an unread badge.
*(Needs the local UUID — see the `/me` open item in §1.)*

---

## 10. Business rules (the parts the shapes don't explain)

**Effective pickup time.** For a child on a date, the server resolves one
"effective pickup time" by precedence: a school **calendar exception** for that
date (a `null` dismissal = no school) → else the regular schedule
(`early_dismissal_days` weekday override → else `default_dismissal_time`) → then
pushed **later** by any of the child's activities that day (practice ending at
5pm makes pickup 5pm). Resolved in the school's timezone, returned as a UTC
datetime (it's `PickupEvent.scheduled_time`). On a no-school day an activity
alone still yields a pickup time.

**Rotation engine.** `generate` walks the date range over the rule's
`cycle_days`, anchored to `start_date`, and assigns each eligible day to the next
family in `order` (round-robin, or repeated by `weight` for weighted). It is
**idempotent and never-overwrite**: a date that already has any assignment
(manual, confirmed, or previously suggested) is skipped, so re-running never
clobbers human decisions. `manual_only` rules generate nothing.

**Trip → pickup cascade.** Starting a trip ensures a `PickupEvent` per child
(`en_route`). A stop going `arrived` propagates to those children's events; a
`TripStopChild.picked_up_at` being set flips the linked event to `picked_up`.
Each of these fires the matching notification (§8). This is a signal chain, so it
behaves identically whether the driver acts over WebSocket or REST.

**Notification triggers (what creates a `Notification`).** Dismissal reminder
(beat poller, per child, ~N min before pickup) · swap requested → target family ·
new chat message → other participants · calendar exception added/edited →
school's families · stop arrived → that stop's families · child picked up →
child's family · SOS → all trip guardians. Each is deduped so re-fires don't
double-notify. The `notification.new` WS broadcast is instant; Expo push is
queued — **except SOS**, which pushes synchronously for real-time delivery.

**SOS fan-out.** Recipients = the trip's guardians (driver + stop-child families
+ group members) minus the raiser. Delivery is triple (push + per-user WS +
trip-channel WS) and bypasses the deferred queue.

---

## 11. Known gaps / not-yet-built

- **No `/me` endpoint** returning the local `User` UUID — see §1. The single
  most likely thing you'll need added early (blocks the notification socket).
- **Media upload is wired (Cloudinary).** Use `POST /children/{id}/photo/`
  (proxy) or `POST /media/signature/` (client-direct signed upload) — see §8.
  Backend defaults to a `fake` Cloudinary backend in dev (`CLOUDINARY_BACKEND`);
  set it to `cloudinary` with real creds to actually store assets.
- **OpenAPI schema is exported** to `schema/openapi.yaml`, and served live at
  `/api/v1/schema/` (+ `/api/v1/schema/swagger-ui/`, `/redoc/`). Point
  `openapi-fetch`/`orval` at it to generate your typed client; the Clerk Bearer
  scheme is included so Swagger's "Authorize" works.
- **SMS/email notification channels are modeled but inert** — only
  `push_enabled` currently affects delivery.
- **Push needs `PUSH_BACKEND=expo`** on the backend to actually reach Expo; dev
  default `fake` no-ops (notifications still persist and stream over WS).
- **No self-serve auth endpoints** — all sign-in/up/reset is Clerk-hosted; the
  backend only verifies tokens.
- **Solo (non-carpool) trips** are supported (`carpool_group: null`), but there's
  no dedicated "start a solo pickup" shortcut beyond `POST /trips/`.

---

## 12. Frontend quick-start

1. **Auth client.** Wrap the app in `@clerk/clerk-expo`'s `ClerkProvider`. Build
   one `openapi-fetch` client whose middleware calls `getToken()` and sets
   `Authorization: Bearer <jwt>`, with base URL `…/api/v1`. Map non-2xx to your
   toast/inline-error handling by reading `error.error.{message,details}` (§3).
2. **Query keys** (mirror `FRONTEND-ARCHITECTURE.md §5`): `['families']`,
   `['children', { family }]`, `['schools']`, `['assignments', groupId, { from, to }]`,
   `['trip', tripId]`, `['trip', tripId, 'latest-location']`, `['pickup-events', { date }]`,
   `['threads']`, `['messages', threadId]` (infinite), `['notifications', { unread }]`.
3. **The Today screen** is just `GET /pickup-events/?date=` — one row per child,
   display-ready (`child_name`, `scheduled_time`, `status`, `pickup_method`). Tap
   a card with an active trip → open `trip/[tripId]`.
4. **Live trip:** hydrate with `GET /trips/{id}/` + `GET /trips/{id}/location/latest/`,
   then open `ws/trips/{id}/` and route incoming events into the cache (§9). If
   the socket won't connect, poll `latest-location` every 10s — same UI. Driver
   mode publishes `location_update` frames (throttle to ~5–10s) and drives stops
   with `stop_status_update`.
5. **Chat:** `useInfiniteQuery` on `GET /chat-threads/{id}/messages/` for history,
   `ws/chat/{id}/` for live send/receive + read receipts. Send optimistically;
   reconcile on the echoed `message.new`.
6. **Push + deep links:** request permission → `POST /device-tokens/` with the
   Expo token → handle taps by reading the notification `data` (§8) and routing.
   Also open `ws/notifications/{myUserId}/` for foreground in-app delivery
   *(pending the `/me` UUID — §1)*.
7. **SOS:** the `SOSButton` posts `POST /sos-alerts/`; the receiving side listens
   on the trip socket's `sos_alert` **and** the notification stream/push, and
   renders the full-screen `SOSBanner` (screen 18) until `resolve`.

> Status strings are your single source of truth for `StatusBadge` — the enums in
> §4 (`scheduled/en_route/arrived/picked_up/missed/cancelled`,
> `suggested/confirmed/swap_pending/…`) map 1:1 to the color law in
> `FRONTEND-ARCHITECTURE.md §6`. Keep them stable and the UI stays consistent.
