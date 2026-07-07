# Backend prompt — Carpool group invites & leaving

Give this to Claude in your **backend** repo (the Django `pickme` project). It
mirrors the existing `FamilyInvite` flow so it should slot in cleanly next to
the family-membership code.

---

## Context

The frontend carpool feature is built and calls these endpoints. Two already
exist and work (`POST /carpool-groups/` and `POST /carpool-groups/join/`). The
following are **new** and currently 404. Implement them exactly as specified so
the app wiring works without changes.

Existing relevant models: `CarpoolGroup` (has `invite_code`), `CarpoolGroupMember`
(fields: `group`, `family`, `role` ∈ `admin|member`, `joined_at`). There is an
existing `FamilyInvite` model + `POST /families/{id}/members/invite` +
`POST /family-invites/accept/` — copy that pattern.

---

## 1. Email a parent an invite to a carpool group

**Endpoint:** `POST /api/v1/carpool-groups/{id}/invite/`

**Auth:** requester must be an **admin** member of the group (403 otherwise).

**Request body:**
```json
{ "email": "parent@example.com" }
```

**Behaviour:**
1. Validate `email` (required, valid email). 400 with `{ "error": { "code": "validation", "details": { "email": ["..."] } } }` on failure.
2. Create a `CarpoolGroupInvite` row:
   - `id` (uuid, pk)
   - `group` (FK → CarpoolGroup, on_delete CASCADE)
   - `email` (EmailField, lowercased)
   - `invited_by` (FK → User)
   - `token` (uuid4, unique, indexed) — the redeem token
   - `status` (`pending | accepted | revoked`, default `pending`)
   - `created_at`, `accepted_at` (nullable)
   - Unique constraint on `(group, email)` where `status="pending"` (re-inviting the same pending email should update/resend, not duplicate).
3. Send an email to `email` containing **both** the group's `invite_code` (so
   they can type it into "Join with a code") **and** a deep link
   `pickme://carpool/accept?token=<token>` for one-tap accept. Use the same mail
   backend the family invite uses (console backend in dev).
4. Fire a notification only if the invited email maps to an existing user
   (optional; not required for v1).

**Response:** `201`
```json
{
  "id": "...", "group": "<groupId>", "email": "parent@example.com",
  "status": "pending", "invite_code": "K7MNP2QR", "created_at": "..."
}
```

## 2. Accept a carpool invite (emailed token)

**Endpoint:** `POST /api/v1/carpool-group-invites/accept/`

**Auth:** the signed-in invited user.

**Request body:** `{ "token": "<uuid>", "family": "<your family id>" }`

**Behaviour:** validate token is `pending` and not expired; add the user's
`family` to the group as a `member` (idempotent if already a member); mark the
invite `accepted` + set `accepted_at`. Mirror `POST /family-invites/accept/`.

**Response:** `200/201`
```json
{ "group": { ...CarpoolGroup }, "member": { ...CarpoolGroupMember } }
```

## 3. Leave a carpool group

**Endpoint:** `POST /api/v1/carpool-groups/{id}/leave/`

**Auth:** any member of the group (removes the **requesting user's** family).

**Behaviour:**
- Delete the requesting user's `CarpoolGroupMember` row for this group.
- **Guard:** if that family is the **only admin** and other members remain,
  block with `409` `{ "error": { "code": "last_admin", "message": "Promote another family to admin before leaving." } }` — OR auto-promote the
  oldest remaining member to admin (pick one; document which). If they're the
  last member overall, deleting the membership (and optionally the empty group)
  is fine.

**Response:** `204 No Content`.

## 4. Serializer additions (list ergonomics — optional but recommended)

Add read-only fields to the **CarpoolGroup** serializer so the app's list and
detail screens don't need extra round-trips:
- `member_count` (int) — `group.members.count()`
- `school_name` (str) — `group.school.name`

The app already tolerates their absence, but they make the group cards show
"3 families" and the school name without N extra requests.

---

## Acceptance checks
- `POST /carpool-groups/{id}/invite/` as a non-admin → 403.
- Invite email is sent (visible in the console backend) and includes the invite code.
- Accept with a valid token adds the family as `member`; re-accepting is a no-op.
- `leave/` removes only the caller's family; last-admin guard behaves as documented.
- `CarpoolGroup` responses include `member_count` and `school_name`.

Please also add/adjust DRF tests alongside the existing carpool tests, and update
`PICKME_API_REFERENCE.md` §6 with these three endpoints and the two new fields.
