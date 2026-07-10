"""E2-2 completion — SFTP + IMAP import transports.

The two transports that migration 064 refused (501) are now built. The properties
that matter:

  1. credentials are NEVER stored in the DB — a schedule names an ENV VAR that
     holds the secret, resolved in-process;
  2. SFTP/IMAP hosts go through the same private-IP refusal as the HTTPS SSRF
     guard, so a schedule can't reach internal infrastructure;
  3. the whole thing reuses the existing hash-skip / commit path, so the
     double-import guard still holds.

The blocking paramiko/imaplib calls are exercised against fakes here; a live SFTP
round-trip is verified against a throwaway container in the commit.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import import_scheduler as sch


def _find_migration(name: str) -> pathlib.Path:
    """Robust to the repo layout (backend/ + database/ siblings) AND the container
    layout (both under /app)."""
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("067_krishna_import_transports.sql")


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# Transports are admitted.
# --------------------------------------------------------------------------

def test_sftp_and_imap_are_now_supported():
    assert set(sch.SUPPORTED_SOURCE_KINDS) == {"https", "sftp", "imap"}
    assert sch.UNSUPPORTED_SOURCE_KINDS == {}


def test_migration_widens_the_check_and_requires_config():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "source_kind in ('https', 'sftp', 'imap')" in sql
    assert "source_config" in sql
    # A non-https transport must carry host + username or the DB refuses it.
    assert "import_schedules_transport_has_config" in sql


# --------------------------------------------------------------------------
# Credentials by env-var name, never plaintext.
# --------------------------------------------------------------------------

def test_credentials_are_resolved_by_env_var_name(monkeypatch):
    monkeypatch.setenv("SCHED_TEST_PW", "s3cret")
    assert sch._resolve_secret({"password_env": "SCHED_TEST_PW"}, "password_env") == "s3cret"
    assert sch._resolve_secret({"password_env": "MISSING_VAR"}, "password_env") is None
    assert sch._resolve_secret({}, "password_env") is None


def test_the_secret_itself_is_never_read_from_the_config():
    """The transport must look up an env var, never trust a plaintext field."""
    for fn in (sch._fetch_sftp_blocking, sch._fetch_imap_blocking):
        code = _code(fn)
        assert "_resolve_secret(" in code
        assert 'config.get("password")' not in code  # never a plaintext password field
        assert 'config["password"]' not in code


# --------------------------------------------------------------------------
# Host safety (SSRF equivalent for sftp/imap).
# --------------------------------------------------------------------------

def test_private_and_loopback_hosts_are_refused():
    for bad in ("127.0.0.1", "localhost", "10.0.0.5", "169.254.169.254", "192.168.1.1"):
        with pytest.raises(sch.FetchError, match="private|loopback|resolve"):
            sch._assert_safe_host(bad)


def test_a_public_host_passes():
    sch._assert_safe_host("example.com")  # resolves to a public IP, must not raise


def test_both_transports_guard_the_host():
    assert "_assert_safe_host(host)" in _code(sch._fetch_sftp_blocking)
    assert "_assert_safe_host(host)" in _code(sch._fetch_imap_blocking)


# --------------------------------------------------------------------------
# SFTP host-key verification is not skipped.
# --------------------------------------------------------------------------

def test_sftp_never_auto_adds_host_keys():
    """AutoAddPolicy would defeat host-key verification and enable MITM. The code
    must use RejectPolicy and only load pinned keys from a configured file."""
    code = _code(sch._fetch_sftp_blocking)
    assert "AutoAddPolicy" not in code
    assert "RejectPolicy" in code


# --------------------------------------------------------------------------
# Dispatch + fetch behaviour, with the blocking libs faked.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_routes_by_source_kind(monkeypatch):
    calls = {}

    async def _https(url):
        calls["https"] = url
        return b"H"

    def _sftp(cfg):
        calls["sftp"] = cfg
        return b"S"

    def _imap(cfg):
        calls["imap"] = cfg
        return b"I"

    monkeypatch.setattr(sch, "fetch_https", _https)
    monkeypatch.setattr(sch, "_fetch_sftp_blocking", _sftp)
    monkeypatch.setattr(sch, "_fetch_imap_blocking", _imap)

    assert await sch.fetch_payload({"source_kind": "https", "source_url": "u", "source_config": {}}) == b"H"
    assert await sch.fetch_payload({"source_kind": "sftp", "source_url": "", "source_config": {"host": "h"}}) == b"S"
    assert await sch.fetch_payload({"source_kind": "imap", "source_url": "", "source_config": {"host": "h"}}) == b"I"
    assert calls["sftp"] == {"host": "h"} and calls["imap"] == {"host": "h"}


@pytest.mark.asyncio
async def test_an_unknown_transport_raises():
    with pytest.raises(sch.FetchError, match="Unsupported source_kind"):
        await sch.fetch_payload({"source_kind": "carrier_pigeon", "source_config": {}})


def test_imap_needs_username_and_a_resolved_password():
    with pytest.raises(sch.FetchError, match="username|password"):
        sch._fetch_imap_blocking({"host": "mail.example.com"})


def test_sftp_needs_a_credential():
    # Host resolves fine (public), but no password_env/private_key_env is set.
    with pytest.raises(sch.FetchError, match="credential|username|path"):
        sch._fetch_sftp_blocking({"host": "example.com", "username": "u", "path": "/x.csv"})


# --------------------------------------------------------------------------
# The route accepts the new kinds and validates config.
# --------------------------------------------------------------------------

def test_the_create_route_accepts_sftp_imap_and_validates_config():
    from app.routes import imports as routes
    code = _code(routes.create_schedule)
    # `email` is aliased to imap.
    assert "'imap' if body.source_kind == 'email'" in code
    # non-https requires host+username, and refuses a private host.
    assert "source_config.host and .username" in code or "requires source_config.host" in code
    assert "_assert_safe_host" in code
    # https still gets its own URL SSRF guard.
    assert "is_safe_url" in code
