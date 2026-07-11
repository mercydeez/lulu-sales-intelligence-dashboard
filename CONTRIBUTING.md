# Contributing

How to develop, test, and ship changes here. Read `TEAM_OWNERSHIP.md` (who owns what),
`GIT_WORKFLOW.md` (branching/PRs), and `PROJECT_STRUCTURE.md` (architecture) alongside
this.

## Prerequisites

- Docker Desktop, Node 20, Python 3.11.
- Demo logins (password `Demo@2026!`): `atharva@retaildemo.app` (super_admin),
  `krishna@retaildemo.app` (regional_manager, Dubai), `yash@retaildemo.app`
  (store_manager, Al Barsha).

## Run it

```powershell
# Full stack (frontend :3000, backend :8000, Swagger :8000/docs)
docker compose up -d

# Frontend hot-reload (compose does NOT hot-reload — run the dev server on host)
cd frontend; npm install --legacy-peer-deps; npm run dev

# Re-trigger a clean DB seed
docker compose down -v && docker compose up -d
```

## Test & typecheck (run before every PR)

```powershell
# Backend — in the container (pinned deps, always correct)
docker exec sales_backend python -m pytest tests/ -v --tb=short
# Backend — locally, in a venv installed from requirements.txt (see trap below)
cd backend; pytest

# Frontend
cd frontend; npx tsc --noEmit; npm run build; npm test
```

CI (`.github/workflows/ci.yml`) runs all of the above plus docker build, a full-stack
smoke test, migration apply/re-apply, a backup/restore drill, and dependency/image
scans. **A PR merges only when CI is green and the CODEOWNERS reviewer approves.**

## Known traps (read these — they cost hours)

- **Units vs AED.** Raw `sales` are **units**; AED revenue is derived
  (`SUM(units × unit_price_aed)`). VOLUME in units, VALUE in AED, never mixed on one
  axis. Align new sales code to `backend/app/services/kpi_service.py` (re-exported by `routes/kpis.py`).
- **Local test env drift.** `requirements.txt` pins `httpx==0.26.0`; a newer global
  httpx (≥0.28) removes the `app=` kwarg and breaks starlette's `TestClient`. Run
  `pytest` in a venv installed from `requirements.txt`, or in the container.
- **No hot reload from compose.** uvicorn has no `--reload` and the frontend image
  serves a prebuilt bundle. Rebuild containers, or run `npm run dev` on host.
- **Migrations auto-apply on boot** (dev/demo) and via `python -m app.commands.migrate`
  (prod). There is no Alembic yet (`alembic/` is empty).

## How to make common changes without touching hub files

The two worst merge-conflict hubs have been refactored away — use these entry points:

- **Add a backend endpoint:** put handlers in a `routes/<domain>.py`, then append one
  `(module.router, "/api/<path>", ["Tag"])` tuple to
  `backend/app/routes/registry.py` — **in your owner block**. Do **not** edit `main.py`.
- **Add a frontend page:** create `app/<route>/page.tsx`, append one entry to
  `frontend/src/config/nav.tsx`, and add its `tKey` to `contexts/LanguageContext.tsx`
  (both `en` and `ar`). Do **not** edit `Sidebar.tsx`.
- **Add a DB migration:** `git pull` first, then create
  `database/migrations/<max+1>_<owner>_<topic>.sql`. Never edit an existing migration.
- **Add a setting/flag:** append to `backend/app/config.py` in an owner-bannered block.

## Coding boundaries

- Stay inside the files your context owns (`TEAM_OWNERSHIP.md`). Touching another
  owner's module? Keep it minimal and request their review (CODEOWNERS will add them).
- Shared hubs (`database.py`, `redis_client.py`, `auth.py`, `components/ui`,
  `apiClient.ts`, contexts) change via **small dedicated PRs** that land fast.
- Only build UI the backend actually supports.

## PR checklist

Before opening a PR (`.github/pull_request_template.md` encodes this):

- [ ] Branch named `<owner>/<epic-id>-<slug>`; rebased on `origin/main`.
- [ ] Backend tests + frontend `tsc`/`build`/tests pass locally.
- [ ] Units/AED discipline respected for any sales/revenue code.
- [ ] New endpoint → `routes/registry.py`; new page → `config/nav.tsx` (+ i18n keys).
- [ ] New migration is additive, numbered `max+1`, idempotent.
- [ ] Tests added/updated; docs updated if behavior or structure changed.
- [ ] Conventional Commit messages; PR is small and single-purpose.
