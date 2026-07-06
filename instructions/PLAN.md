# School Pickup Coordinator — Project Plan

## 1. Problem

Families with kids at different schools (different dismissal times, different buildings, sometimes different districts) struggle to coordinate who's picking up whom, especially when carpooling with other families. This app centralizes: dismissal schedules, carpool rotations, live pickup tracking, and communication between the parents involved in getting kids home safely.

## 2. Core Features (v1 — full feature set)

| Area | Features |
|---|---|
| **Family & Kids** | Multi-parent families, multiple children per family, each child linked to a school + grade, profile photos |
| **Schools & Schedules** | Multiple schools per family, per-school dismissal times, calendar exceptions (early dismissal, holidays, delays) |
| **After-school activities** | Recurring activities per child with their own end time/location, feeding into pickup planning |
| **Carpool** | Carpool groups scoped to a school, rotation rules (round-robin engine), auto-suggested schedules that parents can accept/edit, manual swap requests |
| **Live tracking** | Driver starts a "trip" covering one or more stops/kids, live GPS shown on a map to waiting parents, ETA via Maps API, lightweight status pings (en route / arrived / picked up) for drivers who don't want continuous GPS on |
| **Chat** | Per-carpool-group chat, per-trip "today" thread |
| **Notifications** | Push reminders before dismissal, driver-arrived alerts, swap request alerts, chat alerts |
| **Safety** | SOS alert from a trip, visible to all guardians involved in that trip/group |

## 3. Tech Stack & Rationale

| Layer | Choice | Why |
|---|---|---|
| Mobile app | React Native (Expo) | Cross-platform, good maps/location/push library support |
| Backend API | Django + DRF | Fast to build CRUD-heavy domain models, mature ecosystem |
| Real-time (GPS/chat) | Django Channels + Redis channel layer | DRF has no native WebSocket story; Channels is the standard companion, reuses the same Redis instance |
| Background jobs | Celery + Redis (broker) | Reminders, ETA recalculation, rotation generation, cleanup — all belong off the request/response cycle |
| Auth | Clerk | Handles signup/login/MFA/social login out of the box, with a first-class Expo SDK (`@clerk/clerk-expo`) for React Native; Django verifies the session JWT and mirrors the user locally via webhooks |
| Media | Cloudinary | Avatars, chat attachments — offloads image storage/transform from your servers |
| Maps | Google Maps Platform (Directions, Distance Matrix, Places Autocomplete) + `react-native-maps` | Best-supported combo for RN; Distance Matrix gives you ETA without building your own routing. (Mapbox is a solid, often cheaper, alternative if usage grows — same architecture, swap the SDK) |
| DB | PostgreSQL | Relational data with lots of FKs — this domain is inherently relational |

## 4. User Roles

There's only one account type: **Parent/Guardian**. Kids are records, not accounts, in v1.

- **Family**: has an **owner** (creator) and **members** (co-parents/guardians invited in). Any member can manage children/schedules unless you want to restrict — v1 treats all family members as equal.
- **Carpool Group**: scoped to a school. Has **admins** (can edit rotation rules, remove members) and **members** (can accept/swap assignments, chat, see trips).
- **Driver**: not a fixed role — it's whoever is assigned to a given `CarpoolAssignment`/`Trip` on a given day. Any parent in the group can drive.

## 5. High-Level Architecture

```
┌─────────────────┐         ┌──────────────────────────────────────┐
│  React Native    │  HTTPS  │            Django + DRF               │
│  (Expo) App       │◄───────►│  REST API (auth, CRUD, rotation logic)│
│                   │         │                                        │
│                   │  WSS    │  Django Channels (WebSocket layer)    │
│                   │◄───────►│  - trip location/status broadcast     │
│                   │         │  - chat                                │
└───────┬───────────┘         └───────────────┬────────────────────────┘
        │                                     │
        │ Auth (JWT)                          │
        ▼                                     ▼
┌──────────────┐                    ┌──────────────────┐
│  Clerk        │                    │   PostgreSQL      │
│  Auth         │                    │   (primary DB)     │
└──────────────┘                    └──────────────────┘
       │
       │ webhook (user.created/updated/deleted)
       ▼
  keeps local `users` table in sync
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
                  │    Redis      │   │    Celery      │   │  Cloudinary   │
                  │ (broker +     │   │  workers +      │   │  (media)      │
                  │  channel layer)│   │  beat scheduler │   │               │
                  └──────────────┘   └──────────────┘   └──────────────┘
                                              │
                                              ▼
                                     ┌──────────────────┐
                                     │  Google Maps API   │
                                     │  (ETA, geocoding)   │
                                     └──────────────────┘
```

**Why Channels alongside Celery/Redis:** Celery handles "do this later, once" (send a reminder, recalculate a rotation). Channels handles "keep this connection open and stream events" (a parent watching a driver's dot move on a map, or a live chat). They share Redis but solve different problems — don't try to make one do the other's job.

## 6. Frontend Architecture Overview

- **Auth**: `@clerk/clerk-expo` for session management and prebuilt sign-in/sign-up flows — hands you social login and MFA without building custom screens.
- **Navigation**: stack + tab navigator (Expo Router or React Navigation) — tabs for `Today`, `Carpool`, `Chat`, `Family`, `Settings`.
- **State/data**: React Query (TanStack Query) for REST data + caching; a lightweight store (Zustand) for ephemeral UI/session state; WebSocket events update the React Query cache directly (no separate real-time store needed).
- **Maps**: `react-native-maps` with the Google provider; a `LiveTripScreen` renders the driver's marker updating from WebSocket events, plus stop markers and ETA.
- **Push**: Expo Notifications for device token registration, tied to the `DeviceToken` API.
- **Key screens**: Onboarding/Family setup → Today (dismissal countdowns + today's carpool status) → Trip tracking (map) → Carpool group detail (rotation calendar, swap requests) → Chat → Notifications → Settings.

We can go a lot deeper on frontend screens/state once the backend + OpenAPI schema exist — easier to design data-fetching hooks against a real contract than a hypothetical one.

## 7. Roadmap / Phases

| Phase | Goal |
|---|---|
| 0 | Project scaffold: Django project structure, Supabase JWT auth, Postgres, base deployment pipeline |
| 1 | Families, children, schools, calendar exceptions — pure CRUD |
| 2 | Activities (after-school schedules) |
| 3 | Carpool groups + rotation engine (auto-suggestion + manual override + swaps) |
| 4 | Trips + real-time tracking (Channels, location pings, ETA via Maps API) |
| 5 | Chat |
| 6 | Notifications (push + preferences + Celery beat reminders) |
| 7 | SOS/safety |
| 8 | Media (Cloudinary avatars/attachments), polish, deploy |

Detailed stage-by-stage build checklist is in `BUILD-STAGES.md`.

## 8. Key Architectural Decisions

- **Auth**: Clerk issues short-lived session JWTs; Django never touches passwords. A custom DRF authentication class validates the JWT against Clerk's JWKS and JIT-provisions a local `User` row keyed by `clerk_user_id`. Because Clerk's user store lives entirely outside our Postgres instance (unlike Supabase, which shares the same DB), a webhook (`user.created`/`user.updated`/`user.deleted`, verified via Svix signature) is the primary sync path — JIT-on-request is just a fallback for the gap before the first webhook fires.
- **Clerk Organizations vs. our own `Family` model**: Clerk offers a built-in "Organizations" concept that could map to `Family`, but this schema keeps `Family`/`FamilyMember` as our own tables. Carpool logic joins across families constantly (rotation orders, swap requests), and that's much simpler to query against one local table than to round-trip Clerk's API for group membership on every request.
- **Location data retention**: `LocationPing` rows are high-volume and short-lived in value. Store them, but purge anything older than ~30 days via a nightly Celery task — both for storage cost and because indefinitely retaining kids' pickup location trails is a privacy liability, not just a technical one.
- **Rotation engine is a suggestion generator, not an autocrat**: `CarpoolAssignment` rows can be system-generated (`is_auto_suggested=True`) but always require a human to be at fault-tolerant — swaps and manual overrides are first-class, not edge cases.
- **Trips are multi-stop**: a single driver may pick up kids from more than one school/family in one run, so tracking is modeled as `Trip → TripStop → children`, not `Trip → one child`.

## 9. Non-Functional Notes

- **Time zones**: store all times in UTC; each `School` carries an IANA timezone string for correct local display/reminders.
- **Multi-school families**: a `Child.school` FK plus family-level aggregation ("Today" view merges dismissal times across all of a family's children/schools) — don't assume one school per family anywhere in the schema.
- **Offline drivers**: the mobile app should queue location pings locally and flush on reconnect rather than dropping them — worth designing for from the start rather than retrofitting.
- **WebSocket scaling**: Channels + Redis handles moderate concurrency fine; if this grows large, the channel layer is the first thing to revisit (e.g., Redis Cluster or a dedicated pub/sub broker).
