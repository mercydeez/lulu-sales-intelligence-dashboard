# Account Lifecycle

End-to-end account flows. Backend: `routes/auth.py`, `services/auth_service.py`,
`services/token_store.py`. Frontend pages: `/login`, `/reset-password`,
`/verify-email`, `/accept-invite`.

## Sign up (new tenant)
`POST /api/auth/signup` creates a tenant + owner user and sends a verification email
(single-use `email_verify` token, 3-day TTL). Gate with `ENABLE_SIGNUP`.

## Invite a teammate (into an existing tenant)
1. Admin calls `POST /api/auth/invite` → creates the user and returns a single-use
   **invite link** (`/accept-invite?token=…`, 7-day TTL) plus a temporary password
   (back-compat). Bound to tenant + role + `invited_by`; audited (`user_invited`).
2. Invitee opens the link → `/accept-invite` page → `POST /api/auth/accept-invite`
   with a new password → token consumed (single-use), password set, account
   activated, email marked verified; audited (`invite_accepted`).
3. The temporary-password path still works for environments without email.

## Email verification
Link from email → `/verify-email` → `POST /api/auth/verify-email`. Single-use; a
reused link is rejected. `REQUIRE_EMAIL_VERIFICATION` (default true in prod) governs
whether unverified users are gated.

## Forgot / reset password
1. `POST /api/auth/forgot-password` — always returns the same message (no
   enumeration); if the account exists, emails a single-use reset link (30-min TTL).
2. `/reset-password` page → `POST /api/auth/reset-password` → token consumed
   (single-use), password set, **all existing sessions revoked** (epoch), audited.

## Two-factor (TOTP)
- Enroll: `/2fa/setup` → `/2fa/enable` (scan QR, confirm a code; backup codes issued).
- Login with 2FA: password → `mfa_challenge` → `/2fa/verify` with a TOTP/backup code.
- Disable: `/2fa/disable`.

### Enforcing MFA for admins
`REQUIRE_MFA_FOR_ADMINS=true` blocks admin/owner/super_admin logins until 2FA is
enrolled. **Rollout order to avoid lockout:**
1. Keep the flag **off**.
2. Have each admin enroll 2FA (`/2fa/setup` → `/2fa/enable`).
3. Turn the flag **on**.
Break-glass: set the flag off to let an admin re-enroll, then on again.

## Logout
`POST /api/auth/logout` blacklists the presented token (Redis), checked by the
session-invalidation middleware.

## Known limitation
There is no session/device **listing** UI — auth is stateless (JWT + per-token
blacklist + revocation epoch), and no session table is populated. "Revoke all
sessions" is supported (via the epoch, used on password reset); per-device listing
would require persisting sessions and is tracked as future work.
