# Backend prompt — current user endpoint (`GET /me/`)

Give this to Claude in your **backend** (Django `pickme`) repo. The app uses it to
know which backend `User` you are — needed to tell the driver from watchers on a
trip, label "You" in lists, etc. It's currently unimplemented (404).

## Endpoint

`GET /api/v1/me/`

**Auth:** the signed-in user (same Clerk-JWT auth as every other endpoint).

**Behaviour:** return the current `User` as the standard **User summary** shape
already used when a user is nested elsewhere in the API:

```json
{
  "id": "<user uuid>",
  "full_name": "Sarah Ortiz",
  "email": "sarah@example.com",
  "avatar_url": "https://…" 
}
```

`id` must be the same `User` id that appears as `driver`, `sender`,
`raised_by`, `requested_by`, etc. elsewhere, so the app can compare them.

**Notes:**
- Read-only; no body. 200 on success, 401 if unauthenticated.
- This is the user resolved from the Clerk JWT (the one your auth backend
  provisions/looks up — see `accounts/authentication.py`).
- Optional: also accept `PATCH /api/v1/me/` later for profile edits, but the app
  only needs `GET` right now.

Please add a DRF view + URL (`accounts/urls.py`), a test, and document it in
`PICKME_API_REFERENCE.md` §4.
