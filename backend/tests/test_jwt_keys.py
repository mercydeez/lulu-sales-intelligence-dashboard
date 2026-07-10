"""
E5-6 — JWT RS256 signing, vault-sourced keys, kid rotation, JWKS, and the
config guardrail. Pure: no DB / network / real secrets.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from jose import JWTError, jwt

from app.services import jwt_keys as jk


def _rs_settings(tmp_path, **over):
    """A settings-like object wired for RS256 with one generated key on disk."""
    priv, pub = jk.generate_rsa_keypair()
    kid = over.pop("kid", "k1")
    pubdir = tmp_path / "public"
    pubdir.mkdir(exist_ok=True)
    (pubdir / f"{kid}.pem").write_text(pub)
    base = dict(
        jwt_algorithm="RS256",
        jwt_secret_key="hs-secret-minimum-32-characters-long-xx",
        jwt_allow_hs256_fallback=True,
        jwt_private_key=priv,
        jwt_private_key_path="",
        jwt_public_keys_dir=str(pubdir),
        jwt_active_kid=kid,
    )
    base.update(over)
    return SimpleNamespace(**base), priv, pub, kid


def _hs_settings(**over):
    base = dict(
        jwt_algorithm="HS256",
        jwt_secret_key="hs-secret-minimum-32-characters-long-xx",
        jwt_allow_hs256_fallback=True,
        jwt_private_key="", jwt_private_key_path="",
        jwt_public_keys_dir="", jwt_active_kid="",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _claims(**over):
    c = {"user_id": 1, "type": "access",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    c.update(over)
    return c


# --- RS256 round-trip -------------------------------------------------------
def test_rs256_sign_verify_roundtrip(tmp_path):
    s, priv, pub, kid = _rs_settings(tmp_path)
    kp = jk.KeyProvider.from_settings(s)
    assert kp.active_algorithm == "RS256"
    tok = kp.sign(_claims(role="admin"))
    assert jwt.get_unverified_header(tok)["alg"] == "RS256"
    assert jwt.get_unverified_header(tok)["kid"] == kid
    payload = kp.verify(tok)
    assert payload["user_id"] == 1 and payload["role"] == "admin"


def test_rs256_signing_key_never_leaves_in_jwks(tmp_path):
    s, priv, pub, kid = _rs_settings(tmp_path)
    kp = jk.KeyProvider.from_settings(s)
    jwks = kp.public_jwks()
    assert len(jwks["keys"]) == 1
    k = jwks["keys"][0]
    assert k["kid"] == kid and k["kty"] == "RSA" and k["use"] == "sig" and k["alg"] == "RS256"
    # No private material in the JWKS.
    blob = str(jwks)
    assert "PRIVATE" not in blob and "d" not in {kk for kk in k.keys() if kk == "d"}


# --- rotation ---------------------------------------------------------------
def test_rotation_old_and_new_kid_both_verify(tmp_path):
    # Sign a token with key A, then rotate: active key B, but A's public still in the dir.
    sA, privA, pubA, kidA = _rs_settings(tmp_path, kid="kA")
    kpA = jk.KeyProvider.from_settings(sA)
    tokenA = kpA.sign(_claims())

    # New active key B; keep A's public in the same dir (rotation window).
    privB, pubB = jk.generate_rsa_keypair()
    (tmp_path / "public" / "kB.pem").write_text(pubB)
    sB = SimpleNamespace(**{**sA.__dict__, "jwt_private_key": privB, "jwt_active_kid": "kB"})
    kpB = jk.KeyProvider.from_settings(sB)

    tokenB = kpB.sign(_claims())
    # Verifier B (post-rotation keyset) validates BOTH the old and new tokens.
    assert kpB.verify(tokenA)["user_id"] == 1
    assert kpB.verify(tokenB)["user_id"] == 1
    assert jwt.get_unverified_header(tokenB)["kid"] == "kB"


def test_dropped_old_key_no_longer_verifies(tmp_path):
    sA, privA, pubA, kidA = _rs_settings(tmp_path, kid="kA")
    tokenA = jk.KeyProvider.from_settings(sA).sign(_claims())
    # New keyset dir that does NOT contain kA (old key retired).
    newdir = tmp_path / "public2"
    newdir.mkdir()
    privB, pubB = jk.generate_rsa_keypair()
    (newdir / "kB.pem").write_text(pubB)
    sB = SimpleNamespace(**{**sA.__dict__, "jwt_private_key": privB,
                            "jwt_active_kid": "kB", "jwt_public_keys_dir": str(newdir)})
    with pytest.raises(JWTError):
        jk.KeyProvider.from_settings(sB).verify(tokenA)


# --- HS256 back-compat + fallback control -----------------------------------
def test_hs256_roundtrip():
    kp = jk.KeyProvider.from_settings(_hs_settings())
    tok = kp.sign(_claims())
    assert jwt.get_unverified_header(tok)["alg"] == "HS256"
    assert kp.verify(tok)["user_id"] == 1
    assert kp.public_jwks() == {"keys": []}  # symmetric secret is never published


def test_rs256_accepts_legacy_hs256_when_fallback_on(tmp_path):
    s, *_ = _rs_settings(tmp_path, jwt_allow_hs256_fallback=True)
    kp = jk.KeyProvider.from_settings(s)
    legacy = jwt.encode(_claims(), s.jwt_secret_key, algorithm="HS256")
    assert kp.verify(legacy)["user_id"] == 1


def test_rs256_rejects_hs256_when_fallback_off(tmp_path):
    s, *_ = _rs_settings(tmp_path, jwt_allow_hs256_fallback=False)
    kp = jk.KeyProvider.from_settings(s)
    legacy = jwt.encode(_claims(), s.jwt_secret_key, algorithm="HS256")
    with pytest.raises(JWTError):
        kp.verify(legacy)


# --- algorithm-confusion / none rejection -----------------------------------
def test_algorithm_confusion_public_key_as_hmac_is_rejected(tmp_path):
    # Classic RS256->HS256 attack: forge an HS256 token whose HMAC secret is the
    # PUBLIC key bytes (which an attacker knows). Crafted by hand because jose
    # (correctly) refuses to sign with a public key. Must fail: our HS256 branch
    # verifies with the *shared secret*, never the public key.
    import base64, hashlib, hmac, json
    s, priv, pub, kid = _rs_settings(tmp_path, jwt_allow_hs256_fallback=True)
    kp = jk.KeyProvider.from_settings(s)

    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=")
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = _claims(role="super_admin")
    claims["exp"] = int(claims["exp"].timestamp())
    payload = b64(json.dumps(claims).encode())
    signing_input = header + b"." + payload
    sig = b64(hmac.new(pub.encode(), signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + sig).decode()

    with pytest.raises(JWTError):
        kp.verify(forged)


def test_none_algorithm_is_rejected(tmp_path):
    s, *_ = _rs_settings(tmp_path)
    kp = jk.KeyProvider.from_settings(s)
    # Craft an alg=none token (jose refuses to *decode* it; verify must refuse too).
    import base64, json
    def b64(d): return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    tok = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"user_id": 1}) + "."
    with pytest.raises(JWTError):
        kp.verify(tok)


# --- vault sourcing: private key from a FILE path ---------------------------
def test_private_key_loaded_from_file_path(tmp_path):
    priv, pub = jk.generate_rsa_keypair()
    keyfile = tmp_path / "active.key"
    keyfile.write_text(priv)
    pubdir = tmp_path / "pub"; pubdir.mkdir()
    (pubdir / "kf.pem").write_text(pub)
    s = SimpleNamespace(jwt_algorithm="RS256", jwt_secret_key="x" * 32,
                        jwt_allow_hs256_fallback=False, jwt_private_key="",
                        jwt_private_key_path=str(keyfile), jwt_public_keys_dir=str(pubdir),
                        jwt_active_kid="kf")
    kp = jk.KeyProvider.from_settings(s)
    assert kp.has_signing_key()
    assert kp.verify(kp.sign(_claims()))["user_id"] == 1


# --- config guardrail -------------------------------------------------------
def test_config_rs256_without_key_raises_in_prod():
    from app.config import Settings
    s = Settings(environment="production", jwt_secret_key="x" * 40, secret_key="y" * 40,
                 database_url="postgresql+asyncpg://u:strongpass@db:5432/app",
                 cors_origins="https://app.example.com", use_rls_role=True,
                 jwt_algorithm="RS256")  # no private key / kid
    with pytest.raises(RuntimeError):
        s.validate_security()


def test_config_rs256_with_valid_key_ok_in_prod(tmp_path):
    from app.config import Settings
    priv, pub = jk.generate_rsa_keypair()
    pubdir = tmp_path / "pub"; pubdir.mkdir()
    (pubdir / "kprod.pem").write_text(pub)
    s = Settings(environment="production", jwt_secret_key="x" * 40, secret_key="y" * 40,
                 database_url="postgresql+asyncpg://u:strongpass@db:5432/app",
                 cors_origins="https://app.example.com", use_rls_role=True,
                 redis_self_hosted=False,
                 jwt_algorithm="RS256", jwt_private_key=priv, jwt_active_kid="kprod",
                 jwt_public_keys_dir=str(pubdir), jwt_allow_hs256_fallback=False)
    # Should not raise; RS256 key loads and signs.
    issues = s.validate_security()
    assert not any("RS256" in i and "CRITICAL" in i for i in issues)


def test_config_hs256_in_prod_is_valid_but_logs_nudge(caplog):
    # HS256 + a strong secret must still PASS the secure-config bar (issues == []),
    # while logging a migrate-to-RS256 nudge (log-only, not an issue).
    import logging
    from app.config import Settings
    s = Settings(environment="production", debug=False, jwt_secret_key="x" * 40, secret_key="y" * 40,
                 database_url="postgresql+asyncpg://u:strongpass@db:5432/app",
                 cors_origins="https://app.example.com", use_rls_role=True,
                 redis_self_hosted=False, jwt_algorithm="HS256")
    with caplog.at_level(logging.WARNING, logger="sales_dashboard"):
        issues = s.validate_security()
    assert issues == []
    assert any("HS256" in r.message and "RS256" in r.message for r in caplog.records)
