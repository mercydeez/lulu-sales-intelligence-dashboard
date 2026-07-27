# Runbook — JWT signing keys: RS256, vault, and rotation (E5-6)

**Owner:** Krishna (Platform, Data & Services)

Retail IQ signs its own tokens (access, refresh, MFA challenge, password-reset,
email-verify, SSE stream ticket). This runbook covers migrating from the legacy
symmetric **HS256** scheme to asymmetric **RS256**, sourcing keys from a secret
vault, and rotating them with zero downtime.

Code: `app/services/jwt_keys.py` (key provider), `app/services/auth_service.py`
(sign/verify choke points `_sign`/`_verify`), `app/config.py::validate_security`
(boot guardrail), `GET /api/monitoring/jwks.json` (public keyset),
`scripts/generate_jwt_keys.py` (keygen).

---

## 1. Why RS256

HS256 signs **and** verifies with one shared secret (`JWT_SECRET_KEY`). Anything
that can verify a token can also forge one, so every service holding the secret is
part of the key-compromise blast radius. RS256 splits the trust:

- **Private key** — signs. Held only by the API (ideally injected from a vault at
  runtime, never on disk in the image, never committed).
- **Public key** — verifies. Safe to distribute; published at
  `GET /api/monitoring/jwks.json`. A downstream verifier (worker, public API, a
  future service) validates tokens with the public key and **cannot mint** them.

Tokens carry a key id (`kid`) in their header so multiple keys can coexist during
rotation.

## 2. Configuration

| Variable | Meaning |
|---|---|
| `JWT_ALGORITHM` | `HS256` (default) or `RS256` |
| `JWT_PRIVATE_KEY_PATH` | file the vault writes the private PEM to (**preferred**) |
| `JWT_PRIVATE_KEY` | inline private PEM (alternative; avoid storing in files) |
| `JWT_PUBLIC_KEYS_DIR` | directory of `<kid>.pem` public keys (the rotation set) |
| `JWT_ACTIVE_KID` | key id stamped into newly signed tokens |
| `JWT_ALLOW_HS256_FALLBACK` | accept legacy HS256 tokens during cutover; turn **off** after |

The active private key's own public half is derived automatically, so you do not
have to also place the active public key in `JWT_PUBLIC_KEYS_DIR` (though doing so
is harmless).

**Boot guardrail:** in production/staging, `JWT_ALGORITHM=RS256` with a missing or
unloadable private key, or without `JWT_ACTIVE_KID`, **refuses to boot**
(`validate_security` raises). HS256 in prod is accepted but logs a nudge to migrate.

## 3. Secret vault sourcing

The provider reads key material from an inline env value **or a file path**. The file
path is the integration seam for a real vault — the vault agent writes the secret to
a mounted file and the app reads it:

- **HashiCorp Vault** — Vault Agent / CSI templates the private PEM to
  `/run/secrets/jwt/active.key`; set `JWT_PRIVATE_KEY_PATH` to it.
- **AWS Secrets Manager** — the Secrets Store CSI driver mounts the secret as a file
  (or an init step writes it); same path wiring. On AWS this pairs with the E5-3 UAE
  region (`me-central-1`) so keys stay in-region.
- **Kubernetes Secret** — mount the secret volume read-only at `/run/secrets/jwt`.

`docker-compose.production.yml` mounts `${JWT_KEYS_HOST_DIR:-./secrets/jwt}` →
`/run/secrets/jwt:ro`; point `JWT_KEYS_HOST_DIR` at where your vault materializes the
keys. **Never bake keys into the image or commit PEMs.** The private key file should
be `0600`; `generate_jwt_keys.py` writes it that way.

## 4. Generate a keypair

```bash
# in the backend container or a venv with requirements.txt
python scripts/generate_jwt_keys.py --kid 2026-07 \
    --out-dir /run/secrets/jwt --public-dir /run/secrets/jwt/public
# writes: /run/secrets/jwt/2026-07.key (private, 0600)
#         /run/secrets/jwt/public/2026-07.pem (public)
```

Use a meaningful `kid` (a date like `2026-07` works well — it records when the key
became active).

## 5. Migrate HS256 → RS256 (zero downtime)

The `JWT_ALLOW_HS256_FALLBACK` window lets already-issued HS256 tokens keep working
while new tokens are RS256:

1. **Generate** the first RS256 keypair (§4).
2. **Provision** the private key via the vault (file at `JWT_PRIVATE_KEY_PATH`) and
   the public key into `JWT_PUBLIC_KEYS_DIR`.
3. **Switch** the API: `JWT_ALGORITHM=RS256`, `JWT_ACTIVE_KID=<kid>`,
   `JWT_ALLOW_HS256_FALLBACK=true`. Deploy. New logins get RS256 tokens; existing
   HS256 access/refresh tokens still verify.
4. **Wait** past the longest token lifetime (refresh tokens: up to
   `REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS`, currently 30 days) so no live HS256
   token remains.
5. **Close** the fallback: set `JWT_ALLOW_HS256_FALLBACK=false` and redeploy. The
   symmetric secret is now out of the trust path for verification.

Verify at each step:

```bash
# New tokens are RS256 with a kid:
curl -fsS https://api.yourdomain.com/api/monitoring/jwks.json | jq '.keys[].kid'
# Log in, decode the header of the returned access_token — alg must be RS256.
```

## 6. Rotate an RS256 key (routine, e.g. quarterly or on suspicion)

**Order matters — publish the new public key everywhere BEFORE signing with it**, so
no verifier sees an unknown `kid`:

1. **Generate** a new keypair with a new `kid` (§4), e.g. `2026-10`.
2. **Publish** `2026-10.pem` into `JWT_PUBLIC_KEYS_DIR` on **every** verifier (the
   API, and any service that fetches JWKS). At this point both the old and new public
   keys are present.
3. **Activate**: set `JWT_ACTIVE_KID=2026-10` and point `JWT_PRIVATE_KEY_PATH` at the
   new private key. Deploy the API. New tokens are signed by `2026-10`; tokens still
   in flight signed by the previous kid keep verifying (their public key is still in
   the set).
4. **Wait** past the longest token lifetime (30 days) so nothing signed by the old
   kid remains.
5. **Retire** the old key: remove the old `<kid>.pem` from `JWT_PUBLIC_KEYS_DIR` and
   destroy the old private key in the vault. Redeploy.

Emergency rotation (suspected private-key compromise): do steps 1–3 immediately,
then **shorten the wait** by also invalidating sessions — the logout/blacklist path
(`SessionInvalidationMiddleware` + Redis) and a forced password reset revoke tokens
faster than waiting for natural expiry. Removing the compromised public key
(step 5) as soon as no legitimate token needs it stops all tokens it signed.

## 7. Verification checklist

- [ ] `GET /api/monitoring/jwks.json` lists the expected `kid`(s) — and only public
      key fields (`kty,n,e,kid,use,alg`), never `d` or a PEM.
- [ ] A fresh login's `access_token` header has `alg: RS256` and the active `kid`.
- [ ] Boot logs show no RS256 `CRITICAL` from `validate_security`.
- [ ] During a rotation window, tokens signed by both the old and new kid verify.
- [ ] After closing the HS256 window, a hand-crafted HS256 token is rejected.
- [ ] `test_jwt_keys.py` passes (RS256 round-trip, rotation, HS256 fallback control,
      algorithm-confusion & `none` rejection, JWKS shape, config guardrail).

## 8. Rollback

RS256 is config + key material only — no migration, no schema change.

- **Back to HS256:** set `JWT_ALGORITHM=HS256` and redeploy. `JWT_SECRET_KEY` must
  still be a strong secret. (Only do this if RS256 provisioning failed; it is a
  downgrade.)
- **Bad new key during rotation:** revert `JWT_ACTIVE_KID` / `JWT_PRIVATE_KEY_PATH`
  to the previous key (still in the public set) and redeploy. Tokens signed by the
  bad key stop being minted; keep its public key until those expire, then remove it.

## 8a. Rotation executed once — evidence (2026-07)

A full rotation was exercised end-to-end against the running stack (not just
unit-tested) to satisfy the E5-6 acceptance criterion:

1. Backend booted with `JWT_ALGORITHM=RS256`, `JWT_ACTIVE_KID=2026-07`, keys
   mounted read-only at `/run/secrets/jwt` (private via `JWT_PRIVATE_KEY_PATH`,
   public set via `JWT_PUBLIC_KEYS_DIR`). `POST /api/auth/login` issued a token
   with header `{"alg":"RS256","kid":"2026-07"}`.
2. That token was verified in a **separate process holding only the JWKS JSON**
   fetched from `GET /api/monitoring/jwks.json` — no private key, no app code, no
   shared secret. This is exactly how a downstream worker / public API / third
   party validates: it can verify but cannot forge (the published JWK carries only
   `n`/`e`). Codified as `test_downstream_verifies_with_only_the_jwks`.
3. New key `2026-08` generated; its **public** half added to the keys dir
   alongside `2026-07` (the overlap window). Backend restarted signing with
   `JWT_ACTIVE_KID=2026-08`. JWKS then advertised **both** kids, and tokens
   signed by either verified against the live JWKS.
4. After the old tokens' TTL, `2026-07.pem` is removed from the dir; only new
   tokens verify thereafter (`test_dropped_old_key_no_longer_verifies`).

**Note on defaults:** the app and prod compose keep `JWT_ALGORITHM` defaulting to
`HS256` so existing deployments and the whole test suite are unaffected until an
operator opts in. A live deployment cuts over via the `JWT_ALLOW_HS256_FALLBACK`
window (new tokens RS256, old HS256 still verify), then closes the fallback once
issued HS256 tokens have expired. The config guardrail fails closed in
prod/staging if RS256 is selected without a loadable key + kid.

## 9. Related

- `docs/production/ENVIRONMENT.md` — the JWT signing env table + fail-closed rules.
- `docs/security/SSO.md` — external IdP tokens are verified against the **IdP's**
  JWKS (`services/sso.py`), a separate trust path from our own signing keys.
- `docs/runbooks/DATA_RESIDENCY.md` — keep vault-held keys in the UAE region.
- `app/services/jwt_keys.py`, `scripts/generate_jwt_keys.py`.
