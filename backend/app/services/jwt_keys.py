"""
JWT key provider (E5-6) — asymmetric (RS256) signing with vault-sourced keys,
key-id (`kid`) rotation, and a JWKS view; HS256 stays as a backward-compatible
fallback so a live deployment can cut over without invalidating issued tokens.

Why this exists
---------------
The legacy scheme signed **and** verified every token with one symmetric secret
(`JWT_SECRET_KEY`, HS256). Any service that could *verify* a token could also
*forge* one, so the key-compromise blast radius was the whole fleet. RS256 splits
that: a **private** key signs (held only by the auth service, ideally injected
from a secret vault), and a **public** key verifies (safe to distribute — e.g. via
the JWKS endpoint — to the worker, the public API, or any downstream verifier).

Vault sourcing
--------------
Key material is read from, in order of precedence:
  * an inline PEM env var (`JWT_PRIVATE_KEY` / public keys dir), or
  * a file path (`JWT_PRIVATE_KEY_PATH`) — the canonical "a vault agent
    (HashiCorp Vault / AWS Secrets Manager / mounted k8s secret) writes the PEM
    to a file" pattern.
This module never hardcodes keys and never logs them.

Rotation
--------
Signing uses the active key id (`JWT_ACTIVE_KID`), stamped into the JWT header.
Verification consults a **keyset** (every public key in `JWT_PUBLIC_KEYS_DIR`
as `<kid>.pem`, plus the active private key's own public half). During a rotation
window both the old and new public keys are present, so tokens signed by either
verify; once the old tokens expire the old public key is dropped. See
docs/runbooks/JWT_KEY_ROTATION.md.

Security note (algorithm confusion)
-----------------------------------
`verify()` selects the verification key from the token's declared `alg` and passes
exactly one algorithm to the JWT library. An RS256→HS256 confusion token (signed
with the public key bytes as an HMAC secret) is rejected because the HS256 branch
verifies with the *shared secret*, never a public key — and HS256 is refused
entirely once the fallback is turned off. `alg: none` and any other algorithm are
rejected.
"""
from __future__ import annotations

import os
import hashlib
from typing import Dict, List, Optional, Tuple

from jose import JWTError, jwt, jwk

from app.config import logger

RS256 = "RS256"
HS256 = "HS256"


def _read_pem(inline: str, path: str) -> str:
    """Resolve PEM material from an inline value or a file path (vault-written).
    Inline wins; a path is read lazily. Returns "" when neither is set."""
    if inline and inline.strip():
        return inline.strip()
    if path and path.strip():
        try:
            with open(path.strip(), "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as e:
            logger.error(f"JWT key: could not read key file '{path}': {e}")
            return ""
    return ""


def _derive_public_pem(private_pem: str) -> Optional[str]:
    """Derive the SubjectPublicKeyInfo PEM from a private key PEM."""
    try:
        from cryptography.hazmat.primitives import serialization
        priv = serialization.load_pem_private_key(private_pem.encode(), password=None)
        return priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"JWT key: failed to derive public key from private key: {e}")
        return None


class KeyProvider:
    """Immutable snapshot of the signing/verification material for one config.

    Build with `KeyProvider.from_settings(settings)`. Cheap to hold; parse once.
    """

    def __init__(
        self,
        algorithm: str,
        hs256_secret: str,
        allow_hs256_fallback: bool,
        private_pem: str,
        active_kid: str,
        public_keys: Dict[str, str],
    ) -> None:
        self.algorithm = RS256 if str(algorithm).upper() == RS256 else HS256
        self._hs256_secret = hs256_secret
        self._allow_hs256_fallback = allow_hs256_fallback
        self._private_pem = private_pem
        self._active_kid = active_kid
        self._public_keys = dict(public_keys)  # kid -> public PEM

    # -- construction --------------------------------------------------------
    @classmethod
    def from_settings(cls, settings) -> "KeyProvider":
        algorithm = getattr(settings, "jwt_algorithm", HS256) or HS256
        hs256_secret = getattr(settings, "jwt_secret_key", "") or ""
        allow_fallback = bool(getattr(settings, "jwt_allow_hs256_fallback", True))

        private_pem = _read_pem(
            getattr(settings, "jwt_private_key", "") or "",
            getattr(settings, "jwt_private_key_path", "") or "",
        )
        active_kid = (getattr(settings, "jwt_active_kid", "") or "").strip()

        public_keys: Dict[str, str] = {}
        # 1) every <kid>.pem in the public-keys directory (rotation set)
        keys_dir = (getattr(settings, "jwt_public_keys_dir", "") or "").strip()
        if keys_dir and os.path.isdir(keys_dir):
            for fname in sorted(os.listdir(keys_dir)):
                if not fname.endswith(".pem"):
                    continue
                kid = fname[:-4]
                try:
                    with open(os.path.join(keys_dir, fname), "r", encoding="utf-8") as fh:
                        public_keys[kid] = fh.read().strip()
                except OSError as e:
                    logger.error(f"JWT key: could not read public key '{fname}': {e}")
        # 2) the active private key's own public half (so the dir need not repeat it)
        if private_pem and active_kid:
            derived = _derive_public_pem(private_pem)
            if derived:
                public_keys.setdefault(active_kid, derived)

        return cls(algorithm, hs256_secret, allow_fallback, private_pem, active_kid, public_keys)

    # -- introspection -------------------------------------------------------
    @property
    def active_algorithm(self) -> str:
        return self.algorithm

    @property
    def active_kid(self) -> str:
        return self._active_kid

    def has_signing_key(self) -> bool:
        if self.algorithm == RS256:
            return bool(self._private_pem and self._active_kid)
        return bool(self._hs256_secret)

    def _hs256_accepted(self) -> bool:
        """HS256 is accepted when it's the active mode, or explicitly kept as a
        migration fallback while RS256 is active."""
        return self.algorithm == HS256 or self._allow_hs256_fallback

    # -- sign ---------------------------------------------------------------
    def sign(self, claims: dict) -> str:
        """Sign claims with the active algorithm. RS256 stamps the `kid` header."""
        if self.algorithm == RS256:
            if not self._private_pem or not self._active_kid:
                raise RuntimeError("RS256 selected but no private key / active kid configured")
            return jwt.encode(
                claims, self._private_pem, algorithm=RS256, headers={"kid": self._active_kid}
            )
        return jwt.encode(claims, self._hs256_secret, algorithm=HS256)

    # -- verify -------------------------------------------------------------
    def verify(self, token: str, options: Optional[dict] = None) -> dict:
        """Verify a token, selecting the key from its declared `alg`/`kid`.

        Raises `JWTError` on any failure (unknown/refused alg, bad signature,
        expired, unknown kid). Never verifies an RS256 token with the HMAC secret
        or an HS256 token with a public key (algorithm-confusion safe).
        """
        try:
            header = jwt.get_unverified_header(token)
        except JWTError:
            raise
        alg = (header.get("alg") or "").upper()

        if alg == RS256:
            kid = header.get("kid")
            candidates: List[str] = []
            if kid and kid in self._public_keys:
                candidates = [self._public_keys[kid]]
            elif kid:
                # unknown kid — during rotation a verifier may lag; try all known
                candidates = list(self._public_keys.values())
            else:
                candidates = list(self._public_keys.values())
            if not candidates:
                raise JWTError("no RS256 public key available for verification")
            last_err: Optional[Exception] = None
            for pub in candidates:
                try:
                    return jwt.decode(token, pub, algorithms=[RS256], options=options)
                except JWTError as e:
                    last_err = e
            raise last_err or JWTError("RS256 verification failed")

        if alg == HS256:
            if not self._hs256_accepted():
                raise JWTError("HS256 tokens are not accepted (fallback disabled)")
            if not self._hs256_secret:
                raise JWTError("no HS256 secret available for verification")
            return jwt.decode(token, self._hs256_secret, algorithms=[HS256], options=options)

        raise JWTError(f"unsupported JWT algorithm: {alg or 'none'}")

    # -- JWKS ---------------------------------------------------------------
    def public_jwks(self) -> dict:
        """JWKS ({"keys": [...]}) of the RS256 public keys, for downstream
        verifiers. Empty when running HS256 (a symmetric secret is never
        published)."""
        keys = []
        for kid, pub in self._public_keys.items():
            try:
                d = jwk.construct(pub, RS256).to_dict()
                d.update({"kid": kid, "use": "sig", "alg": RS256})
                keys.append(d)
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"JWT key: could not render JWK for kid '{kid}': {e}")
        return {"keys": keys}


# -----------------------------------------------------------------------------
# Cached default provider (built from get_settings()). Rebuilds when the relevant
# settings change (so tests / rotation reloads are picked up).
# -----------------------------------------------------------------------------
_PROVIDER: Optional[KeyProvider] = None
_PROVIDER_SIG: Optional[str] = None


def _settings_signature(s) -> str:
    parts = [
        str(getattr(s, "jwt_algorithm", "")),
        str(getattr(s, "jwt_active_kid", "")),
        str(getattr(s, "jwt_public_keys_dir", "")),
        str(getattr(s, "jwt_private_key_path", "")),
        str(getattr(s, "jwt_allow_hs256_fallback", "")),
        hashlib.sha256((getattr(s, "jwt_private_key", "") or "").encode()).hexdigest(),
        hashlib.sha256((getattr(s, "jwt_secret_key", "") or "").encode()).hexdigest(),
    ]
    return "|".join(parts)


def get_key_provider(settings=None) -> KeyProvider:
    """Return the process-wide key provider, rebuilding it when config changes."""
    global _PROVIDER, _PROVIDER_SIG
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    sig = _settings_signature(settings)
    if _PROVIDER is None or sig != _PROVIDER_SIG:
        _PROVIDER = KeyProvider.from_settings(settings)
        _PROVIDER_SIG = sig
    return _PROVIDER


def reset_key_provider() -> None:
    """Drop the cached provider (used by rotation reloads / tests)."""
    global _PROVIDER, _PROVIDER_SIG
    _PROVIDER = None
    _PROVIDER_SIG = None


# -----------------------------------------------------------------------------
# Key generation helper (used by scripts/generate_jwt_keys.py and tests).
# -----------------------------------------------------------------------------
def generate_rsa_keypair(key_size: int = 2048) -> Tuple[str, str]:
    """Return (private_pem, public_pem) for a fresh RSA keypair (PKCS8 / SPKI)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem
