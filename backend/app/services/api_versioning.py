"""E6-6 — the public API's version lifecycle.

The public surface has always been mounted at `/api/public/v1/*`. What was
missing was not the version *segment* but the version *contract*: a promise
about what we may change, an announcement channel for retiring a version, and a
guard that stops an unversioned endpoint being added by accident.

DESIGN NOTE — why there is no `ENABLE_DEPRECATION_HEADERS` flag.
A flag defaulting to off would ship the machinery dormant, which is the same
"built but never wired" trap we removed elsewhere in this codebase. Instead the
behaviour is driven purely by DATA: the lifecycle dates in config. Today no
version carries a date, so this module is inert — every v1 response is a plain
200 with no extra headers. The day we retire v1, setting one env var makes the
announcement real, on a code path that has been under test since this commit.

The state machine, per version (RFC 9745 `Deprecation`, RFC 8594 `Sunset`):

    no dates configured          -> current    : 200, no lifecycle headers
    deprecated_on <= today       -> deprecated : 200 + Deprecation + Link
    ... and sunset_on in future  -> deprecated : 200 + Deprecation + Sunset + Link
    sunset_on <= today           -> sunset     : 410 Gone

410 is deliberate. Once we have told integrators a version is gone on a date, a
request after that date must not silently keep working — that would teach them
the date was a bluff, and the next sunset would be ignored.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException, Request, Response

from app.config import get_settings

# The version every public route is mounted under. One constant, so the string
# is not re-typed into each decorator and cannot drift between them.
PUBLIC_API_VERSION = "v1"

# Every version this build can serve, oldest first.
SUPPORTED_PUBLIC_VERSIONS: tuple = ("v1",)

# Public routes that intentionally carry no version segment. Discovery has to be
# stable forever — an integrator asks "which versions still exist?" precisely
# when the one they were using has 410'd, so this endpoint can never be versioned.
UNVERSIONED_PUBLIC_PATHS: frozenset = frozenset({"/versions"})

_VERSION_IN_PATH = re.compile(r"^/api/public/(v\d+)(?:/|$)")


def version_from_path(path: str) -> Optional[str]:
    """The version segment of a public API path, or None if it carries none."""
    m = _VERSION_IN_PATH.match(path)
    return m.group(1) if m else None


def _lifecycle_dates(version: str) -> tuple[Optional[date], Optional[date]]:
    """(deprecated_on, sunset_on) for a version, from config. Unknown -> (None, None)."""
    s = get_settings()
    if version == "v1":
        return s.public_api_v1_deprecated_on, s.public_api_v1_sunset_on
    return None, None


def _http_date(d: date) -> str:
    """An IMF-fixdate, as both RFC 9745 and RFC 8594 require."""
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def lifecycle(version: str, today: Optional[date] = None) -> Dict[str, object]:
    """The published lifecycle of one version. Pure — `today` is injectable so the
    state machine is testable without waiting for 2027."""
    today = today or datetime.now(timezone.utc).date()
    deprecated_on, sunset_on = _lifecycle_dates(version)

    if sunset_on and sunset_on <= today:
        status = "sunset"
    elif deprecated_on and deprecated_on <= today:
        status = "deprecated"
    else:
        status = "current"

    return {
        "version": version,
        "status": status,
        # Announced dates are published even before they take effect, so an
        # integrator can see a deprecation coming rather than discover it.
        "deprecated_on": deprecated_on.isoformat() if deprecated_on else None,
        "sunset_on": sunset_on.isoformat() if sunset_on else None,
    }


def supported_versions(today: Optional[date] = None) -> List[Dict[str, object]]:
    return [lifecycle(v, today=today) for v in SUPPORTED_PUBLIC_VERSIONS]


async def public_api_lifecycle(request: Request, response: Response) -> None:
    """Router-level dependency on the public API.

    Announces a version's retirement in headers, and refuses to serve it once the
    sunset date has passed. A path with no version segment (discovery) is exempt.
    """
    version = version_from_path(request.url.path)
    if not version:
        return

    s = get_settings()
    state = lifecycle(version)
    status = state["status"]

    link = f'<{s.public_api_policy_url}>; rel="deprecation"'

    if status == "sunset":
        # The 410 carries the same headers a machine client was already reading
        # while the version was merely deprecated, so nothing has to special-case
        # the transition. A body alone would only help a human.
        raise HTTPException(
            status_code=410,
            headers={
                "Deprecation": _http_date(date.fromisoformat(state["deprecated_on"])),
                "Sunset": _http_date(date.fromisoformat(state["sunset_on"])),
                "Link": link,
            },
            detail={
                "error": "api_version_sunset",
                "message": (
                    f"Public API {version} was retired on {state['sunset_on']}. "
                    f"See {s.public_api_policy_url} for the migration path."
                ),
                "version": version,
                "sunset_on": state["sunset_on"],
                "supported_versions": [
                    v["version"] for v in supported_versions() if v["status"] != "sunset"
                ],
                "policy": s.public_api_policy_url,
            },
        )

    if status == "deprecated":
        # RFC 9745: the date the version *became* deprecated.
        response.headers["Deprecation"] = _http_date(date.fromisoformat(state["deprecated_on"]))
        response.headers["Link"] = link
        if state["sunset_on"]:
            # RFC 8594: the date it will stop responding.
            response.headers["Sunset"] = _http_date(date.fromisoformat(state["sunset_on"]))
