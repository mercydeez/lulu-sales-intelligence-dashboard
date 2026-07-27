# Git Workflow

A **trunk-based** workflow for three developers working in parallel. Optimized for a
clean, linear history and minimal merge conflicts.

## The model in one picture

```
main (protected trunk)
  ├─ atharva/e3-3-store-health    (1–3 days) ─┐
  ├─ krishna/e6-1-sql-views       (1–3 days) ─┼─► PR → CI + CODEOWNERS review → squash-merge
  └─ yash/e4-analytics-ui         (1–3 days) ─┘
releases: annotated tag on main (e.g. v0.4.0)
hotfixes: hotfix/<slug> off main → PR → squash-merge → tag
```

- **`main` is the single source of truth.** It is always releasable and protected
  (required CI + 1 CODEOWNERS approval, linear history / no direct pushes).
- **Feature branches are short-lived (1–3 days).** Long-lived branches are the enemy
  of parallel work — they diverge and produce big conflicts.

## Rollout (one-time)

The team currently works on `prototype-evolution-accuracy-bullmq`. To adopt this
workflow:

1. Open a PR `prototype-evolution-accuracy-bullmq → main`; get it green and merge.
2. Enable branch protection on `main`: require the CI checks in
   `.github/workflows/ci.yml`, require 1 CODEOWNERS approval, require linear history,
   disallow direct pushes.
3. Everyone branches off `main` from then on.

## Branch naming

```
<owner>/<epic-id>-<short-slug>
```

Examples: `krishna/e6-1-sql-views`, `atharva/e3-3-store-health`, `yash/e4-analytics-ui`.

- **Owner prefix** = your first name (matches CODEOWNERS routing).
- **Epic id** ties the branch to a workstream in `docs/EXECUTION_BLUEPRINT_12M.md` /
  `TEAM_OWNERSHIP.md`.
- Special prefixes: `hotfix/<slug>` (urgent prod fix off `main`), `chore/<slug>`,
  `docs/<slug>`.

## Commits

- **Conventional Commits:** `type(scope): summary` — `feat`, `fix`, `refactor`,
  `docs`, `test`, `chore`, `perf`, `build`, `ci`.
  Examples: `feat(decisions): store-health score`, `refactor(routes): registry`.
- Small, logically-scoped commits. Don't mix a refactor with a feature.
- Co-authorship trailer for AI-assisted commits is fine and encouraged.

## Pull requests

- **One workstream per PR**, kept small (aim < ~400 lines changed). Small PRs review
  fast and rebase cleanly.
- **Required to merge:** all CI jobs green **and** 1 approval from the CODEOWNERS-
  assigned reviewer.
- **Squash-merge** so each PR is one commit on `main` — keeps history linear and
  bisectable. Delete the branch after merge.
- Fill in `.github/pull_request_template.md` (CI, owner review, units/AED, tests, docs).

## Rebase, not merge

- Keep your branch current by **rebasing on `main`**, at least daily and always right
  before opening/updating a PR:
  ```
  git fetch origin
  git rebase origin/main
  # resolve, then:
  git push --force-with-lease
  ```
- **Never** merge `main` into your feature branch (no merge commits on features).
- PRs land via **squash-merge**; the trunk stays linear.

## Merge order (conflict avoidance)

When multiple PRs touch a **shared hub**, sequence them smallest-first so others
rebase onto the change immediately:

1. Land shared-file PRs **first and fast**: `routes/registry.py`, `config/nav.tsx`,
   `config.py`, locale files, `types/index.ts`.
2. Announce the merge so others `git rebase origin/main` right away.
3. Only then land the larger feature PRs that depend on them.

## Migrations — avoiding number collisions

Migrations are the lowest-conflict area (additive files) **if** you follow one rule:

```
git fetch origin && git rebase origin/main      # get the latest migrations
N = max(existing number in database/migrations) + 1
create database/migrations/<N>_<owner>_<topic>.sql
```

- **Never edit an already-merged migration** — add a new one.
- If two people race for the same number, the later one renames to the next free
  number (a rename, not a content conflict).

## Conflict resolution

- Prefer **rebase** (linear history) over merge commits.
- If two owners must change the same hub, the smaller PR lands first; the second
  rebases. Coordinate on the shared file's steward (see `TEAM_OWNERSHIP.md`).
- When a conflict is in a file you don't own, pull in the owner rather than guessing.

## Pull frequency

- Rebase on `origin/main` **at least once a day** and before every PR update.
- Keep branches alive no longer than ~3 days; split large work into stacked small PRs.

## Hotfixes

1. `git switch main && git pull`
2. `git switch -c hotfix/<slug>`
3. Fix + test → PR → squash-merge to `main` → tag (`vX.Y.Z+1`).
4. No separate release branch — `main` is the release line.

## Releases

- Cut a release by tagging `main`: `git tag -a vX.Y.Z -m "..." && git push --tags`.
- No long-lived `release/*` branches (trunk-based). If a release must be stabilized
  without freezing trunk, cut a short-lived `release/vX.Y` branch, tag from it, and
  cherry-pick fixes — the exception, not the rule.
