# Frontend Architecture — School Pickup Coordinator

React Native (Expo), styled and structured to match the shadcn/ui philosophy via its React Native ecosystem equivalents.

## 1. Library Stack

| Concern | Library | Notes |
|---|---|---|
| Framework | Expo (SDK latest) + Expo Router | File-based routing, native tabs/stacks, deep-link support out of the box (needed for notification taps → specific screens) |
| Components | **React Native Reusables** | The shadcn/ui port for RN — same component names, copy-paste model (you own the code), built on rn-primitives |
| Primitives | **rn-primitives** | Radix UI's accessibility/composition model ported to RN — comes with Reusables, powers dialogs, dropdowns, tabs, etc. |
| Styling | **NativeWind v4** | Tailwind classes in RN; theme via CSS variables in `global.css`, exactly like shadcn theming on web |
| Icons | **phosphor-react-native** | Same Phosphor set you know; use `weight="regular"` as default, `weight="fill"` for active states |
| Server state | TanStack Query v5 | All REST data: caching, invalidation, optimistic updates, pull-to-refresh |
| Client state | Zustand | Small ephemeral stores only: active trip session, WS connection status, draft chat input |
| Forms | react-hook-form + zod | Zod schemas can be generated from the backend's OpenAPI schema later — one source of truth |
| API client | openapi-fetch (or orval) | Typed client generated from drf-spectacular's exported schema |
| Auth | @clerk/clerk-expo | Session, prebuilt flows, `getToken()` feeds the API client + WS connect |
| Maps | react-native-maps (Google provider) | Trip tracking screen |
| Realtime | Native `WebSocket` + a thin `useTripSocket` / `useChatSocket` hook | No heavy client lib needed; hooks write incoming events into the React Query cache |
| Push | expo-notifications | Token registration → `POST /device-tokens/`, tap handling → deep link |
| Location (driver) | expo-location + expo-task-manager | Background location while a trip is `in_progress`, throttled to ~every 5–10s |
| Media | expo-image-picker → Cloudinary unsigned upload preset | Avatars, chat attachments |
| Animation | react-native-reanimated | Pulsing driver marker, bottom sheet, status transitions |
| Bottom sheets | @gorhom/bottom-sheet | Trip screen's draggable ETA/stops sheet |

**One deliberate exclusion**: no Redux. Server state lives in React Query, ephemeral state in Zustand — a global store would just duplicate the cache.

## 2. Project Structure

```
app/                          # Expo Router — file-based routes
  (auth)/
    sign-in.tsx
    sign-up.tsx
  (onboarding)/
    create-family.tsx
    add-children.tsx
    add-school.tsx
  (tabs)/
    _layout.tsx               # Tab bar (Phosphor icons)
    index.tsx                 # Today
    carpool/
      index.tsx               # Groups list
      [groupId]/
        index.tsx             # Group detail + rotation calendar
        settings.tsx          # Rotation rule editor (admin)
    chat/
      index.tsx               # Threads list
      [threadId].tsx          # Conversation
    family/
      index.tsx               # Family hub
      child/[childId].tsx     # Child detail + activities
    settings/
      index.tsx
      notifications.tsx
  trip/[tripId].tsx           # Live tracking (modal-style, outside tabs)
  swap/[requestId].tsx        # Swap request respond screen (deep-link target)
components/
  ui/                         # Reusables-owned components (button, card, dialog, badge, ...)
  today/                      # ChildPickupCard, DismissalCountdown, ...
  trip/                       # TripMap, DriverMarker, StopList, TripBottomSheet, SOSButton
  carpool/                    # RotationDayCard, SwapRequestCard, RotationOrderEditor
  chat/                       # MessageBubble, MessageInput, ThreadListItem
  shared/                     # Avatar, StatusBadge, EmptyState, ErrorState, Screen
hooks/
  api/                        # Generated + wrapped React Query hooks per resource
  useTripSocket.ts
  useChatSocket.ts
  useNotificationSocket.ts
  useDriverLocation.ts        # Background location publisher (driver side)
lib/
  api-client.ts               # openapi-fetch instance + Clerk token injection
  ws.ts                       # WS connect/reconnect/backoff helper
  cloudinary.ts
  theme.ts                    # Color tokens mirrored from global.css
stores/
  tripSession.ts              # Zustand: active trip id, socket status
  ui.ts
global.css                    # NativeWind theme variables (light + dark)
```

## 3. Screens (complete inventory)

| # | Screen | Purpose | Key components |
|---|---|---|---|
| 1 | Sign in / Sign up | Clerk prebuilt flows | Clerk components |
| 2 | Onboarding: Create family | Name family, becomes owner | Form, Button |
| 3 | Onboarding: Add children | Name, school picker (Places autocomplete for new schools), photo | Form, Avatar upload, SchoolPicker |
| 4 | **Today** (tab home) | Per-child card: resolved pickup time, method, live status; tap card → trip if active | ChildPickupCard, DismissalCountdown, StatusBadge |
| 5 | **Live Trip** | Map + driver marker + stops bottom sheet + ETA + message driver + SOS | TripMap, TripBottomSheet, SOSButton |
| 6 | Driver Trip mode | Same screen, driver variant: start/end trip, mark arrived/picked-up per stop, tracking-mode toggle (live GPS vs status-only) | StopActionRow, TrackingModeToggle |
| 7 | Carpool groups list | Groups across user's families + join-by-code | GroupCard, JoinCodeDialog |
| 8 | Carpool group detail | Week/month rotation calendar, confirmed/suggested tags, swap buttons, pending swaps | RotationDayCard, SwapRequestCard |
| 9 | Rotation rule editor (admin) | Rotation type, cycle days, drag-to-reorder families, weights, generate button | RotationOrderEditor (draggable list) |
| 10 | Swap respond | Deep-link target from push: accept/reject | SwapRequestCard (expanded) |
| 11 | Chat threads list | Group + trip threads, unread badges | ThreadListItem |
| 12 | Conversation | Messages, image attach, read receipts | MessageBubble, MessageInput |
| 13 | Family hub | Members + roles, invite by email, children list | MemberRow, InviteForm, ChildRow |
| 14 | Child detail | Profile, school, activities CRUD | ActivityRow, ActivityForm |
| 15 | School detail | Dismissal time, calendar exceptions list/add | ExceptionRow |
| 16 | Notifications center | In-app list, mark read, deep links | NotificationRow |
| 17 | Settings: notification prefs | Per-type toggles (push/sms/email) | PreferenceRow (Switch) |
| 18 | SOS active state | Full-screen alert takeover for recipients: who, where, resolve | SOSBanner |

## 4. Component System

**From React Native Reusables (add via CLI, then own the code):**
`Button`, `Card`, `Badge`, `Avatar`, `Dialog`, `AlertDialog` (SOS confirm), `Tabs`, `Switch`, `Input`, `Textarea`, `Select`, `Skeleton` (loading states), `Separator`, `Progress`, `Toast/Sonner-equivalent`.

**Custom domain components (built on those + primitives):**

- `ChildPickupCard` — avatar with per-child `color_tag` ring, name, resolved time, `StatusBadge`, method icon (Phosphor: `Car`, `House`, `Clock`, `Bus`, `PersonSimpleWalk`)
- `StatusBadge` — single source of truth mapping every status enum (`scheduled/en_route/arrived/picked_up/missed`) to color + icon; used on Today, Trip, and Rotation screens so status language is identical everywhere
- `TripMap` — map, stop pins, driver marker with Reanimated pulse, auto-fit bounds
- `TripBottomSheet` — driver header, ETA chip, `StopList`; snap points 25/50/90%
- `RotationDayCard` — left color rail (confirmed=green, suggested=amber), family name, tag, swap button
- `RotationOrderEditor` — draggable family list with weight steppers ("drives 2x")
- `MessageBubble` — mine/theirs variants, image support, timestamp, read ticks
- `SOSButton` — deliberately oversized, red, requires `AlertDialog` confirm; never restyled by theme
- `EmptyState` / `ErrorState` — consistent empties with a Phosphor icon + one-line copy + action

## 5. Data Layer Patterns

**Query keys** — hierarchical, invalidation-friendly:
```ts
['families'], ['families', id],
['children', { family }],
['assignments', groupId, { from, to }],
['trip', tripId], ['trip', tripId, 'latest-location'],
['threads'], ['messages', threadId],       // infinite query
['pickup-events', { date }],
['notifications', { unread }]
```

**WebSocket → cache, one direction:** socket hooks never hold their own state. An incoming `location_update` does `queryClient.setQueryData(['trip', tripId, 'latest-location'], ping)`; `stop_status_update` patches `['trip', tripId]`; `message.new` appends to the messages infinite query and invalidates `['threads']`. UI components just subscribe to queries — they don't know or care whether data arrived by REST or WS. This is the single most important pattern in the app; it keeps real-time from becoming a parallel state system.

**Optimistic updates** where the action is user-owned and low-conflict: sending a chat message, marking a stop picked up, accepting a swap. Rollback on error via React Query's `onError` context.

**Offline/reconnect:** the WS helper does exponential backoff; on reconnect, refetch `['trip', tripId]` and `['trip', tripId, 'latest-location']` to close the gap. Driver-side pings queue in the Zustand trip store while offline and flush in order on reconnect.

**Polling fallback:** if a WS connection can't be established (hostile networks), the trip screen degrades to polling `latest-location` every 10s — same UI, worse latency, no separate code path in components.

## 6. Design System — Uber-Style Color, Type, Feel

Modeled on Uber's design language ("Base" design system) — a deliberate fit, since Uber solved the same design problem this app has: glanceable real-time logistics, high-stakes status, viewed one-handed on a phone in motion.

### Feel

**Monochrome-first, color-as-signal.** The interface is black, white, and gray. Color appears only when it carries meaning — a live trip, a confirmation, an alert. This is the core Uber move: because the canvas is neutral, the moment anything colored appears, the eye goes straight to it. Combined with:

- Big status, small chrome — status and times are the visual heroes, navigation recedes
- Bold black headlines, roomy whitespace, flat surfaces (borders and elevation, not decorative shadows)
- One primary action per screen: a full-width **black button** (white in dark mode) — the signature Uber CTA
- Motion is informational only: driver marker, ETA ticks, sheet gestures
- Min 44pt touch targets, extreme contrast, legible in daylight at arm's length

### Color tokens (Uber Base palette, as NativeWind CSS variables)

```css
:root {
  /* Light mode */
  --background: 0 0% 100%;           /* pure white */
  --foreground: 0 0% 0%;             /* pure black */
  --card: 0 0% 100%;                 /* white cards, separated by borders not shadows */
  --card-secondary: 0 0% 96%;        /* #F6F6F6 — gray panels, list rows */
  --primary: 0 0% 0%;                /* BLACK is the primary — buttons, active tab */
  --primary-foreground: 0 0% 100%;
  --muted: 0 0% 93%;                 /* #EEEEEE */
  --muted-foreground: 0 0% 46%;      /* #757575 */
  --border: 0 0% 89%;                /* #E2E2E2 */
  --accent: 221 88% 55%;             /* #276EF1 — Uber's blue: live/interactive/link */
  --success: 152 94% 33%;            /* #05A357 — Uber green: confirmed, picked up */
  --warning: 42 100% 63%;            /* #FFC043 — Uber yellow: pending, suggested */
  --destructive: 8 100% 44%;         /* #E11900 — Uber red: SOS, missed ONLY */
  --radius: 8px;                     /* tighter than typical — Uber is crisp, not bubbly */
}

.dark {
  --background: 0 0% 8%;             /* #141414 — near-black, not pure black */
  --foreground: 0 0% 100%;
  --card: 0 0% 12%;                  /* #1F1F1F */
  --card-secondary: 0 0% 20%;        /* #333333 */
  --primary: 0 0% 100%;              /* inverted: WHITE buttons on dark */
  --primary-foreground: 0 0% 0%;
  --muted: 0 0% 20%;
  --muted-foreground: 0 0% 69%;      /* #AFAFAF */
  --border: 0 0% 20%;
  --accent: 221 88% 61%;             /* blue lifted slightly for dark contrast */
  /* success/warning/destructive keep hue, lightness nudged up */
}
```

**Status color law** (enforced by `StatusBadge`), now stricter because the canvas is monochrome:
- **Blue (#276EF1)** = live/in-motion (en route, driver marker, active trip) and interactive links
- **Green (#05A357)** = done (confirmed, arrived, picked up)
- **Yellow (#FFC043)** = pending (suggested assignments, awaiting swap) — dark text on yellow, never white
- **Red (#E11900)** = SOS and missed pickups only, never decorative
- Everything else is black/white/gray. If a screen has more than one accent color visible at rest, something is misusing the palette.

**Map treatment**: desaturated gray map style (Google Maps custom JSON style, Uber-like) so the blue driver marker and black stop pins are the only saturated elements — this is most of what makes Uber's trip screen feel like Uber.

**Per-child color tags** (`child.color_tag`): keep, but muted — thin avatar-ring accents from a desaturated 8-swatch set, so they read as identity labels and never compete with status colors.

### Typography

Uber uses its proprietary "Uber Move" typeface, which isn't licensable — **Inter is the standard stand-in** (same grotesque skeleton, excellent RN support). The Uber flavor comes from the scale and weight contrast, not the font file: oversized bold headlines against quiet regular body text.

| Token | Size/weight | Use |
|---|---|---|
| display | 28 / Bold, tight | Screen titles ("Today") — bigger and bolder than before, the Uber headline move |
| title | 18 / Bold | Card headings, driver name |
| body | 15 / Regular | Default text |
| label | 13 / Medium | Buttons, badges, tab labels |
| caption | 12 / Regular, muted-foreground | Timestamps, sublabels |
| numeric-hero | 24 / Bold, tabular-nums | ETA and countdown — tabular so digits don't jitter as they tick |

### Iconography (Phosphor)

`regular` weight everywhere, `fill` for active tab + active statuses. Core mapping: `House` (Today), `Car` (Carpool/driving), `ChatCircle` (Chat), `UsersThree` (Family), `GearSix` (Settings), `MapPin` (stops), `Bell` (notifications), `Siren` (SOS), `ArrowsLeftRight` (swap), `CheckCircle` (picked up/confirmed), `Clock` (pending).

### Component feel details

- Cards: 8px radius, **flat** — 1px `--border` in light mode, slightly lighter surface in dark mode; no drop shadows except the trip bottom sheet
- Buttons: 48–52px height, radius 8, **black filled** primary (white in dark), gray `--card-secondary` filled secondary, thin-outline tertiary; destructive red reserved for SOS
- List rows over floating cards where content is dense (rotation calendar, chat threads) — full-width rows with hairline separators, the Uber list idiom
- Bottom tab: 5 items, icon + 10px label, active = black (white in dark) fill icon; inactive = `--muted-foreground`
- Bottom sheet: white/near-black surface, drag handle, 16px top radius — the one surface allowed a shadow
- Skeletons over spinners for list loads; spinner only for actions
- Haptics (expo-haptics): light impact on stop-status changes, success notification on "picked up", heavy on SOS

### Dark mode

First-class at launch, not a fast-follow — the token system above is symmetric, and dark mode is arguably this app's *primary* mode for early-morning and winter-evening pickups. Follow the system setting by default (`useColorScheme`), with a manual override in Settings. The two non-obvious pieces: a second map style JSON for dark (Uber ships dark maps, not dimmed light maps), and yellow badges keep dark text in both modes.

## 7. Real-Time UX Rules

- Driver marker interpolates between pings (Reanimated) rather than teleporting — ~5s of smoothing makes 5–10s ping intervals feel continuous
- ETA text updates in place, no layout shift (fixed-width tabular numerals)
- Status-only trips (no GPS) show the same screen minus the live marker: stops list + last status + timestamp, so both tracking modes share one mental model
- "Last updated Xs ago" appears if no ping for >30s; the marker dims at >60s — silence is information and should be visible, not hidden
- Chat messages appear optimistically with a subtle pending state; failed sends get an inline retry

## 8. Build Order (frontend stages)

1. Scaffold: Expo + Router + NativeWind + Reusables init + Clerk + theme tokens
2. Auth + onboarding flow (family, children, school picker)
3. Today screen with mocked API → swap to generated client once OpenAPI schema lands
4. Family hub + child/activities CRUD
5. Carpool: groups, rotation calendar, rule editor, swaps
6. Trip screen (parent view) with WS hook + map; then driver mode + background location
7. Chat
8. Notifications: push registration, deep links, prefs
9. SOS, polish pass, haptics, light/dark parity audit (both modes ship at launch)
