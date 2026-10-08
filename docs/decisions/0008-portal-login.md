# 0008 — How users log in to the portal

- Status: **Accepted for Phase 1**; SSO deferred until a customer asks.
- Date: 2026-10-09 (Phase 1.7)
- Affects: `backend/app/auth/`, `backend/app/api/auth.py`, `backend/app/api/deps.py`

Closes the "login method" open decision in rebuild-plan §8 (blocks 1.7).

## Decision

- **Username + password** stored in our store; password hashed with
  **scrypt** (stdlib `hashlib`, salted, parameters stored with the hash).
- On login the backend issues a **signed, expiring session token**
  (HMAC-SHA256 over `{username, tenant_id, exp}`, `SESSION_SECRET`, default
  12 h). Not a JWT library — 40 lines of stdlib we can explain line by line.
- The browser gets it as an **HttpOnly, SameSite=Strict cookie** (`acme_session`),
  `Secure` everywhere except local plain-http dev. Scripts may send the same
  token as `Authorization: Bearer`.
- Every request re-reads the user, so deleting or moving a user takes effect
  immediately, not at token expiry.

## Why

- Cookie, not header-only: the live stream uses `EventSource`, which cannot
  set request headers; a cookie is sent automatically.
- Stateless signed token, not server-side sessions: every uvicorn worker can
  verify it without shared state.
- Same error and same timing for "no such user" and "wrong password".

## Not decided yet

- SSO (Azure AD / Google): add as a second way to obtain the same session
  token when a customer needs it.
- Logout of all sessions at once: rotate `SESSION_SECRET` (logs everybody out).
- Login rate limiting: belongs in the reverse proxy (Phase 4).
