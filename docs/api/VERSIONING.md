# Public API versioning & deprecation policy

**Status:** in force
**Applies to:** every endpoint under `/api/public/`
**Current version:** `v1` — no deprecation announced
**Implementation:** `backend/app/services/api_versioning.py`, tested in `backend/tests/test_api_versioning.py`

---

## The contract

The public API is versioned in the path: `/api/public/v1/...`. The version is a
promise about the **response shape**, not about the numbers inside it — your
data changes, the schema does not.

Within a version we may:

- add a new endpoint;
- add a new **optional** field to a response;
- add a new **optional** query parameter;
- relax a validation rule (accept input we previously rejected);
- fix a wrong number (see *Corrections*, below).

Within a version we will **not**:

- remove or rename a field;
- change a field's type, or its units;
- change the meaning of an existing field;
- add a required request parameter;
- tighten validation so a request that worked yesterday fails today;
- change an endpoint's HTTP status codes for the same input.

**Write your client to ignore unknown fields.** Additive change is the whole
point of a version, and a client that rejects unrecognised keys will break on a
change this policy explicitly permits.

### Units are part of the contract

VOLUME metrics are in **units**; VALUE metrics are in **AED**. A field will
never silently switch between them. If we need the other measure we add a new,
differently-named field.

### Corrections

If a published number is *wrong* — a bug in the arithmetic, not a change of
definition — we will fix it inside the current version rather than preserve a
falsehood for compatibility. Fixes that change any previously-returned value are
called out in the changelog. This is the one case where a value you depend on
can move without a version bump, and we consider shipping a known-wrong number
the worse failure.

---

## Discovery

```
GET /api/public/versions        # no API key required, never versioned
```

```json
{
  "current": "v1",
  "supported": [
    { "version": "v1", "status": "current", "deprecated_on": null, "sunset_on": null }
  ],
  "policy": "https://github.com/mercydeez/lulu-sales-intelligence-dashboard/blob/main/docs/api/VERSIONING.md"
}
```

This endpoint is deliberately **unauthenticated and unversioned**. You need it
most at the moment your version stops answering — which is exactly when you
cannot call your version, and possibly when your key has lapsed. It exposes no
tenant data.

`status` is one of `current`, `deprecated`, `sunset`.

---

## Lifecycle

A version moves through three states. The transition is driven by two dates;
both are published through `/versions` **as soon as they are decided**, so a
deprecation is visible before it takes effect.

| State | What you get | What it means |
|---|---|---|
| `current` | `200`, no lifecycle headers | Nothing to do. |
| `deprecated` | `200` + `Deprecation`, `Sunset`, `Link` headers | Still works. Start migrating. |
| `sunset` | `410 Gone` + the same headers | It is gone. |

### Headers

On a deprecated version, every successful response carries:

```
Deprecation: Sun, 31 Jan 2027 00:00:00 GMT      (RFC 9745 — when it became deprecated)
Sunset:      Sat, 31 Jul 2027 00:00:00 GMT      (RFC 8594 — when it stops answering)
Link:        <.../docs/api/VERSIONING.md>; rel="deprecation"
```

The `410` response carries the **same three headers**, so a client that watches
`Sunset` needs no special case for the day the version actually disappears.

> **Known limitation.** These headers ride on the response of the versioned
> endpoint. A request that fails authentication (`401`) is rejected before a
> body is produced and will not carry them. Read the lifecycle from
> `/api/public/versions`, not from a failed call.

### Guarantees on notice

**Enforced by the code** (the service refuses to start otherwise):

- A version is **announced as deprecated before it is retired**. The
  configuration cannot express a sunset without a prior deprecation date, and
  the sunset must be strictly later.

**Committed to by us, not enforced by the code:**

- Minimum notice of **6 months** between `deprecated_on` and `sunset_on`.
- We will not sunset the only `current` version. A successor ships, and is
  `current`, before its predecessor is deprecated.

The 6-month floor is deliberately *not* a startup assertion. A version retired
for a security reason may have to go with less notice, and a check that forced
us to either lie in the config or ship a known-vulnerable endpoint would make
things worse. Ordering is a correctness property and is enforced; duration is a
commercial promise and is kept by people.

### Why `410`, and not "keep serving quietly"

Once we have told you a version disappears on a date, serving it after that date
teaches every integrator that our dates are theatre — and the *next* sunset,
the one that matters, gets ignored. The date is enforced.

---

## Operating this (maintainers)

The machinery is always live. It is silent today because no version carries a
lifecycle date — not because a feature flag is off. Announcing a deprecation is
a configuration change, on a code path that has been under test since it landed:

```bash
# 1. Announce. v1 keeps serving 200s, now with Deprecation + Link headers.
PUBLIC_API_V1_DEPRECATED_ON=2027-01-31

# 2. Commit to a retirement date (>= 6 months later). Adds the Sunset header.
PUBLIC_API_V1_SUNSET_ON=2027-07-31

# 3. Nothing. On 2027-07-31 the version starts answering 410 by itself.
```

Setting `PUBLIC_API_V1_SUNSET_ON` without `PUBLIC_API_V1_DEPRECATED_ON`, or a
sunset on/before the deprecation, raises at startup.

### Adding `v2`

1. Mount the new routes under `/v2/` on `public_api.router`.
2. Add `"v2"` to `SUPPORTED_PUBLIC_VERSIONS` and point `PUBLIC_API_VERSION` at it.
3. Extend `_lifecycle_dates()` with the `v2` settings.
4. Only then announce `v1`'s deprecation.

`tests/test_api_versioning.py` fails if a public route is added without a
version segment, so an unversioned endpoint cannot reach `main` by accident.

---

## Scope: what is *not* versioned

Only `/api/public/*` is a versioned, supported contract.

Everything under `/api/<domain>` (`/api/kpis`, `/api/sales`, `/api/analytics`, …)
is the **dashboard's private backend**. It is consumed by our own first-party
frontend, which ships in the same release as the backend, and it changes without
notice. It is not documented, not stable, and not supported for third-party use.
Building against it will break you.

If you need something the dashboard has and the public API lacks, ask for it to
be added to `/api/public/v1` — that is the surface we are willing to keep still.
