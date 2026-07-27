<!-- Keep PRs small and single-purpose. See CONTRIBUTING.md + GIT_WORKFLOW.md. -->

## What & why

<!-- One or two sentences. Link the workstream/epic (e.g. E6-1) from EXECUTION_BLUEPRINT_12M.md. -->

## Owner / area

<!-- Which bounded context does this touch? (see TEAM_OWNERSHIP.md) -->

## Checklist

- [ ] Branch named `<owner>/<epic-id>-<slug>`; rebased on `origin/main`.
- [ ] Backend tests pass (`pytest tests/`) and/or frontend `tsc --noEmit` + `npm run build` + `npm test` pass.
- [ ] Units/AED discipline respected for any sales/revenue code (VOLUME=units, VALUE=AED, never mixed).
- [ ] New endpoint added via `backend/app/routes/registry.py` (not `main.py`).
- [ ] New page added via `frontend/src/config/nav.tsx` + i18n keys (not `Sidebar.tsx`).
- [ ] New migration is additive, numbered `max+1`, idempotent (no edits to existing migrations).
- [ ] Tests added/updated; docs updated if behavior or structure changed.
- [ ] Stayed within my owned modules, or requested the owner's review for anything outside them.
- [ ] Conventional Commit title; PR is small and single-purpose.

## Notes for the reviewer

<!-- Anything a CODEOWNERS reviewer should focus on, or seams touched that another owner should confirm. -->
