"""Sync least-privilege DB role passwords from the environment at migrate time.

The deploy blocker this fixes: migrations create (and, on a fresh volume,
RE-assert) hardcoded DEV passwords on the non-owner roles — `app_rw` gets
'app_rw_dev_pass' (020), `worker_rw` gets 'worker_rw_dev_pass' (029/035) and
`sage_ro` gets 'sage_ro_dev_pass' (023). The production compose, however, hands
the API and the diagnostics worker operator-chosen secrets (`RLS_DATABASE_URL`,
`WORKER_DATABASE_URL` built from `WORKER_DB_PASSWORD`, `SAGE_DATABASE_URL`).
Result on a real deploy: the roles keep their dev passwords, every worker/API
connection fails auth, and the operator had to run manual ALTER ROLEs buried in
the docs.

`sync_role_passwords()` closes the gap. It runs at the end of every migration
pass (see services/migration_runner.run_migrations — the single choke point
shared by the one-shot `python -m app.commands.migrate` job AND the
RUN_MIGRATIONS_ON_STARTUP lifespan path), on the OWNER/superuser engine, and
ALTERs each role's password to match what the environment says the connecting
services will use:

    worker_rw  <- env WORKER_DB_PASSWORD (the value the compose file
                  interpolates into WORKER_DATABASE_URL); falls back to the
                  password inside WORKER_DATABASE_URL itself
    app_rw     <- the password parsed OUT of RLS_DATABASE_URL (there is
                  deliberately no separate env var for it)
    sage_ro    <- the password parsed OUT of SAGE_DATABASE_URL

URL passwords are parsed with SQLAlchemy's `make_url` — the SAME parser the
engines consuming those URLs use — so the role password is set to exactly the
value the service will authenticate with, %-decoding included (e.g. %40 -> @)
and characters like '#', '?' or '/' preserved rather than truncated at
(`urllib.parse.urlsplit` + `unquote` is the fallback if make_url refuses the
string). Each source is read from the process environment first, then from the
pydantic settings (so a value supplied only via the backend's .env file still
counts). NOTE: the sync runs in whichever process applies migrations — that
process's environment must actually carry these variables (the dedicated
`migrate` job in production).

A pair is skipped silently when its source is absent/empty (dev volumes keep
the migration defaults; in production/staging an empty set logs a WARNING so a
mis-wired migrate job cannot fail silently) and skipped with an info log when
the role does not exist yet. The sync is idempotent and safe to run on every
boot. It NEVER raises: a failed sync is a loud error log, not a crashed
migrate step — the connecting service's own auth failure will surface the
problem regardless.

Secret-safety:

- The password value is never interpolated into SQL by Python. The ALTER
  statement is built SERVER-side via
  ``SELECT format('ALTER ROLE %I PASSWORD %L', :role, :pw)`` (bind parameters;
  Postgres-native identifier/literal quoting), fetched back as a string, and
  executed through the driver with ``exec_driver_sql`` — no client-side bind
  parsing, so passwords containing ':' or '%' cannot be misread as parameters.
- Python log lines carry only the role name, never the value and never a URL.
  Error details are scrubbed of every known secret (including the
  quote-doubled form %L produces) before logging.
- Postgres statement logging is suppressed for the syncing transaction with
  ``SET LOCAL log_statement = 'none'`` and
  ``SET LOCAL log_min_duration_statement = -1`` so the ALTER text (which embeds
  the quoted password) never lands in the server log. Both settings are
  superuser-only (PGC_SUSET); the migrate/owner connection is the bootstrap
  superuser, so this normally succeeds. If the server refuses (e.g. managed
  Postgres where the owner is not a true superuser), the sync retries WITHOUT
  the suppression and proceeds with the ALTER anyway — in that case be aware
  the statement text MAY appear in the Postgres server log, depending on the
  server's log_statement / log_min_duration_statement configuration.
"""
import logging
import os
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from sqlalchemy import text
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

# The roles whose passwords the environment may own. worker_rw's secret arrives
# as a plain env var (or inside WORKER_DATABASE_URL); app_rw's and sage_ro's
# only exist inside the operator's full URLs (no separate env vars — do not
# invent any).
_WORKER_ROLE = "worker_rw"
_APP_ROLE = "app_rw"
_SAGE_ROLE = "sage_ro"

# Built server-side so quoting is Postgres-native (%I identifier, %L literal).
# CASTs pin the bind parameter types — asyncpg cannot infer types for
# format()'s VARIADIC "any" arguments.
_BUILD_ALTER_SQL = text(
    "SELECT format('ALTER ROLE %I PASSWORD %L', "
    "CAST(:role AS text), CAST(:pw AS text))"
)
_ROLE_EXISTS_SQL = text("SELECT 1 FROM pg_roles WHERE rolname = :r")


class _LogSuppressionRefused(Exception):
    """SET LOCAL log_statement/log_min_duration_statement was refused
    (superuser-only settings). The refusal ABORTS the surrounding transaction,
    so the caller must retry the whole sync in a fresh transaction without the
    suppression."""


def _env_or_setting(name: str) -> Optional[str]:
    """Read a config value from the process environment first, then from the
    pydantic settings field of the same (lowercased) name — this covers values
    supplied only through the backend's .env file, which never appear in
    os.environ."""
    from_env = os.environ.get(name)
    if from_env:
        return from_env
    try:
        from app.config import get_settings
        return getattr(get_settings(), name.lower(), None) or None
    except Exception:
        return None


def _password_from_url(url: Optional[str]) -> Optional[str]:
    """Parse the password out of a database URL.

    Primary parser is SQLAlchemy's make_url — the exact parser the app's
    engines apply to the same string — so the ALTER sets the role to the very
    value the service will authenticate with: %-encoded characters decoded
    (%40 -> @) and characters like '#', '?' or '/' kept intact (urlsplit would
    truncate at them). Falls back to urlsplit + unquote when make_url refuses
    the string. Returns None when there is no parseable password."""
    url = (url or "").strip()
    if not url:
        return None
    try:
        parsed = make_url(url).password
        if parsed:
            return str(parsed)
    except Exception:
        pass
    try:
        fallback = urlsplit(url).password
    except ValueError:
        return None
    if not fallback:
        return None
    return unquote(fallback)


def _password_from_url_env(var_name: str) -> Optional[str]:
    """The password inside the URL held by `var_name` (env, then settings).
    None => skip the pair. A URL that is set but carries no parseable password
    is loudly skipped — silently syncing nothing would hide a typo."""
    url = _env_or_setting(var_name)
    if not url:
        return None
    parsed = _password_from_url(url)
    if parsed is None:
        logger.error(
            "[role-password-sync] %s is set but carries no parseable password — "
            "skipping its role's password sync", var_name,
        )
    return parsed


def _desired_pairs() -> List[Tuple[str, str]]:
    """(role, password) pairs the environment wants asserted. A pair whose
    source is absent/empty is simply not in the list (dev no-op)."""
    pairs: List[Tuple[str, str]] = []
    worker_pw = os.environ.get("WORKER_DB_PASSWORD") or _password_from_url_env("WORKER_DATABASE_URL")
    if worker_pw:
        pairs.append((_WORKER_ROLE, worker_pw))
    app_pw = _password_from_url_env("RLS_DATABASE_URL")
    if app_pw:
        pairs.append((_APP_ROLE, app_pw))
    sage_pw = _password_from_url_env("SAGE_DATABASE_URL")
    if sage_pw:
        pairs.append((_SAGE_ROLE, sage_pw))
    return pairs


def _scrubbed(message: str, secrets) -> str:
    """Redact every known secret from an error message before it can reach a
    log — exception text can echo statement fragments. Also scrubs the
    quote-doubled variant Postgres %L quoting produces (' -> '')."""
    for value in secrets:
        if not value:
            continue
        for variant in (value, value.replace("'", "''")):
            message = message.replace(variant, "***")
    return message


def _warn_if_production_has_no_sources() -> None:
    """A production migrate job with NO password sources is almost always a
    wiring mistake (the env vars were given to the api/worker services but not
    to the process running migrations) — say so instead of no-opping silently."""
    try:
        from app.config import get_settings
        environment = (get_settings().environment or "").lower()
    except Exception:
        environment = ""
    if environment in ("production", "staging"):
        logger.warning(
            "[role-password-sync] no role-password sources found (WORKER_DB_PASSWORD / "
            "WORKER_DATABASE_URL / RLS_DATABASE_URL / SAGE_DATABASE_URL are all unset for "
            "THIS process) — DB roles keep their migration-default dev passwords. If the "
            "API/worker connect with operator-chosen secrets, make sure the process that "
            "applies migrations receives those variables."
        )


async def _sync_role(conn, role: str, password: str, suppress_statement_logging: bool) -> bool:
    """ALTER one role's password inside an already-open transaction.

    Returns True when an ALTER ran, False when the role does not exist yet.
    Raises _LogSuppressionRefused when the server rejects the SET LOCALs (the
    transaction is aborted at that point — retry without suppression)."""
    if suppress_statement_logging:
        # Superuser-only settings: keep the ALTER (whose text embeds the quoted
        # password) out of the Postgres server log. SET LOCAL scopes them to
        # this transaction only.
        try:
            await conn.execute(text("SET LOCAL log_statement = 'none'"))
            await conn.execute(text("SET LOCAL log_min_duration_statement = -1"))
        except Exception as exc:
            raise _LogSuppressionRefused() from exc

    exists = await conn.execute(_ROLE_EXISTS_SQL, {"r": role})
    if exists.scalar() is None:
        logger.info(
            "[role-password-sync] role %s does not exist — skipping "
            "(its migration has not created it yet)", role,
        )
        return False

    # ALTER ROLE cannot take bind parameters, so have Postgres build the
    # statement with its own quoting (format %I/%L), then execute the returned
    # string through the driver: exec_driver_sql performs no bind-parameter
    # parsing, so ':' or '%' inside the quoted literal stay inert.
    built = await conn.execute(_BUILD_ALTER_SQL, {"role": role, "pw": password})
    alter_sql = built.scalar()
    await conn.exec_driver_sql(alter_sql)
    logger.info("[role-password-sync] synced password for role %s", role)
    return True


async def sync_role_passwords(engine=None) -> int:
    """Assert the environment-owned role passwords on the database.

    Runs after every migration pass (both the dedicated migrate job and the
    startup path). Idempotent; never raises. Returns the number of roles whose
    password was (re)asserted — 0 is normal in dev, where no env is set.

    ``engine`` defaults to the app's owner/superuser engine; injectable for
    tests."""
    pairs = _desired_pairs()
    if not pairs:
        # Dev / unset environment: the migration defaults stand. In production
        # this is loud — see the helper.
        _warn_if_production_has_no_sources()
        return 0

    if engine is None:
        from app.services.database import engine as app_engine
        engine = app_engine

    synced = 0
    for role, secret in pairs:
        try:
            try:
                async with engine.begin() as conn:
                    did = await _sync_role(conn, role, secret, suppress_statement_logging=True)
            except _LogSuppressionRefused:
                logger.warning(
                    "[role-password-sync] server refused SET LOCAL log_statement "
                    "(superuser-only) — retrying the sync for role %s without log "
                    "suppression; the ALTER text may appear in the Postgres server "
                    "log (see module docstring)", role,
                )
                async with engine.begin() as conn:
                    did = await _sync_role(conn, role, secret, suppress_statement_logging=False)
            if did:
                synced += 1
        except Exception as exc:  # noqa: BLE001 — must never crash the migrate step
            detail = _scrubbed(f"{type(exc).__name__}: {exc}", [s for _, s in pairs])
            logger.error(
                "[role-password-sync] FAILED to sync the password for role %s — the "
                "connecting service will fail auth until this is resolved (%s)",
                role, detail,
            )
    return synced
