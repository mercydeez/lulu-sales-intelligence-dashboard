# `features/` — feature-first modules

Feature-specific logic (data hooks, feature components, typed API calls) lives
here, organized by product feature rather than by technical layer. This keeps
page files thin and moves fetching/formatting into reusable, testable hooks.

```
features/
  <feature>/
    hooks/       # data + behavior hooks (useBriefing, useDecisions, …)
    components/  # feature-specific presentation (composed from components/ui + components/workflow)
    api.ts       # typed calls for this feature (thin wrappers over lib/apiClient)
    types.ts     # feature-local types
```

## Rules

- **Hooks own data.** A page/zone should call a hook (`const { data, loading, error, reload } = useX()`),
  not inline `fetch`/`apiGet`. Hooks return a consistent `{ data, loading, error, reload }` shape.
- **Presentation stays generic where possible.** Reuse `components/ui`, `components/workflow`,
  `components/ai`; only put here what is genuinely feature-specific.
- **Backend is frozen.** These modules consume existing endpoints; they never imply new backend
  capability.
- **Incremental adoption.** Do NOT migrate everything at once. When a phase touches a feature
  (e.g. P1 touches Home), extract that feature's hooks/components here. Leave untouched features
  where they are until a phase reaches them.

## Cross-cutting logic stays elsewhere

- Navigation/IA → `lib/nav/`
- Shell (rails, utility bar) → `components/shell/`
- Shared UI primitives / states → `components/ui/`
- Shared workflow objects → `components/workflow/` (P2)
- Shared AI blocks → `components/ai/` (P1/P2)
