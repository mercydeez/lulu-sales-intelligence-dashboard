# Sage Copilot — Architecture & Phasing

**Owner:** Atharva (AI / Sage / Decision / Briefing / Role-Experience vertical)
**Status:** Phase 1 implemented (this branch). Phases 2–6 planned.
**Reads with:** `TEAM_OWNERSHIP.md`, `DEVELOPMENT_CONTRACT.md`, `PROJECT_STRUCTURE.md`,
`docs/product/ROLE_EXPERIENCE_BLUEPRINT.md`, `docs/production/AI_SAFETY.md`,
`docs/SAGE_V3_MASTER_PROMPT.md`.

---

## 1. Context — why this change

Sage today is a **floating right-side chat panel**: request/response only,
route-unaware, two endpoints (`/api/ai/chat/stream`, `/chat/clear`). The product
vision is an **AI-first operating system for retail** — Sage proactively briefs
executives, surfaces the decisions that need them, and becomes the primary
interface, with the backend **Role Experience Engine fully describing the
frontend** (navigation, homepage, widgets, assistant mode, quick actions).

Crucially this is **not a greenfield design — it implements the repo's own
blueprint.** `ROLE_EXPERIENCE_BLUEPRINT.md` already specifies the role config
record, the Five-Questions homepage grammar, server-driven zone layouts, persona
packs (the de-facto `assistant_mode`), and per-role quick actions. The engines a
copilot needs already exist and are grounded + tested: briefing, decisions/triage,
findings, ROI, forecast, action drafts, the measure loop. What was missing:
(a) the **config keys** that let the backend drive the whole experience,
(b) a **proactive composition layer**, and (c) the **copilot surface** that
replaces chatbot-first UX.

**Decisions of record:**
1. The executive experience maps to **`super_admin` via a config record** — zero
   RBAC/schema change, no cross-owner dependency. A dedicated `ceo`/`employee`
   role is a later interface request to Krishna.
2. Proactivity (Phase 2) uses **compute-on-read + Redis cache** — the feed is
   waiting when the user arrives; a real scheduler is a later upgrade that needs
   Krishna's `main.py` lifespan coordination.
3. **No breaking changes, no whole-subsystem rewrites** (contract §3.1): every
   change is additive, versioned, and fails open to legacy behavior.

---

## 2. Current implementation (pre-Phase-1 baseline)

- **`services/role_experience.py`** — `_CONFIGS` per role (`store_manager`,
  `regional_manager`, dormant `procurement_manager`, `_default`). Fields:
  `key, home, decision_scope, persona{…,prompt_fragment}, zones[], kpis[],
  nav[]|null, notifications{…}`. `resolve_config()` deep-copies + unknown→default.
- **`routes/experience.py`** — `GET /api/experience` = config + `context`. No
  version, and it **shipped `persona.prompt_fragment`** (a system-prompt fragment)
  to the client.
- **`contexts/ExperienceContext.tsx`** — fetches the config, **fails open**
  (error → `config:null` → legacy behavior everywhere).
- **`app/today/page.tsx`** — role-agnostic renderer, but `ZONE_REGISTRY` was a
  **closed set of 5** (verdict/kpis/decisions/approvals/stock).
- **`Sidebar.tsx`** — renders the server nav manifest when `config.nav != null`
  (labels via `t(item.tKey)`), else the full 23-item list, client-filtered.
- **`ChatBot.tsx` + `AIProvider` + `AIToggleButton`** — a floating pill + a
  right-side slide-in panel; chat/voice gated by hardcoded `hasRole` checks.
- **`CommandPalette.tsx`** — hardcoded `navItems` + 2 procurement actions;
  **ignored the experience config.**
- Everything AI is request/response; nothing consumes `notifications.brief_hour_gst`.

---

## 3. Target architecture

### 3.1 Experience API v2 (the contract that drives everything)

`GET /api/experience` now returns a **versioned, complete** description of the
experience. Every field the backend owns; the frontend renders it.

```jsonc
{
  "version": 2,
  "role": "super_admin",
  "key": "executive",
  "home": "/today",
  "decision_scope": "chain",
  "assistant_mode": "copilot",            // panel | copilot | hidden
  "persona": { "name","title","tagline","greeting","voice" },  // NO prompt_fragment
  "nav": [ {"key","tKey","label","href","icon"} ] | null,      // sidebar manifest
  "zones": [ {"type","props"} ],          // v1 alias, still emitted
  "homepage": { "layout": "focus", "zones": [ {"type","props"} ] },
  "kpis": [ {"key","label","source","field","format"} ],
  "quick_actions": [ {"key","label","href","icon"} ],
  "ai_context": { "focus": ["revenue","profit","risks","growth"], "scope": "All stores" },
  "capabilities": { "ai_chat": true, "voice": true },          // rendering hints
  "notifications": { "brief_hour_gst": 7, "quiet_hours": [22,6], "tiers": [...] },
  "context": { "accessible_store_count": 40 }
}
```

Deliberate deviations from the raw ask, for correctness:
- **`permissions` are echoed only as `capabilities`** (rendering hints).
  Authorization never moves client-side — the server still enforces every AI call
  (`routes/ai.py`), and `capabilities` can only *narrow* the client gate, never
  widen it (ADR-006).
- **`ai_context` carries display/routing metadata, not prompt text.** Prompt
  fragments are server-only (see §3.6); shipping them discloses the system prompt
  and widens the injection surface.
- **Backward compatibility:** `version` is additive; every v1 field is preserved;
  `homepage.zones` mirrors the top-level `zones`; missing v2 fields are filled
  with safe defaults at resolve time; the client fail-open path is untouched.

### 3.2 Open homepage widget registry

`ZONE_REGISTRY` (a closed 5-entry const) → **`components/copilot/registry.tsx`**,
an extensible registry: `registerWidget(s)` / `resolveWidget`. Surfaces populate
it; unknown types resolve to `null` and are skipped. This makes the homepage
**forward-compatible** — the backend can name a widget (`business_health`,
`risks`, `growth`, `recommendations`) that a given build doesn't ship yet without
breaking the page, and Phase 2/3 feed widgets register without editing a central
switch.

### 3.3 Sage Copilot feed (Phase 2 — proactive layer)

New `services/sage_copilot.py` + `routes/copilot.py` → `GET /api/ai/copilot/feed`.
A **pure `build_feed(raw)`** (mirrors `briefing.py`/`roi.py`) composes, per role
scope: briefing verdict, top-3 triaged decisions, risks, opportunities,
cost-of-inaction, recommended actions, business-health snapshot — all from
existing grounded engines, **LLM-free on the proactive path** (the copilot's
front door cannot hallucinate). Compute-on-read + Redis cache keyed by
tenant/role/scope/period; Redis down → compute live. Feed widgets register into
§3.2.

### 3.4 Copilot shell (Phase 4)

`assistant_mode` drives the shell: `copilot` → Sage surface primary (feed widgets
+ embedded chat input); `panel` → current behavior (default, fail-open); `hidden`
→ no AI affordance. Wired now (§4); the surface redesign is Phase 4.

### 3.5 RAG-ready abstractions (Phase 5 — design only)

`services/rag/base.py` (`Chunk{content,source_ref,source_type,permissions,score}`
+ a `KnowledgeSource` protocol) and `services/rag/registry.py` (named source
registry wrapping today's FTS `documents` source unchanged). `permissions` on
`Chunk` is the RBAC-aware-retrieval seam. Ingestion pipeline + pgvector embeddings
+ document ACLs are **explicitly deferred**; the interface is the deliverable.

### 3.6 Security posture (unchanged invariants, one hardening)

NL→SQL guard (SELECT-only, `sage_*` allow-list, tenant GUC), `sage_ro`
least-privilege, RBAC scope threaded into every node, units≠AED (ADR-002),
evidence + disclosure on every answer, zero-LLM deterministic floor. **New:**
persona prompt fragments never leave the server (`resolve_config` strips
`prompt_fragment`; `get_system_prompt` still reads it from the registry); the
proactive feed is LLM-free; low confidence → "I don't have enough evidence".

---

## 4. Phase 1 — what shipped on this branch

All changes additive, versioned, fail-open. **Files (all Atharva-owned except the
two sanctioned appends):**

| File | Change | Reason |
|---|---|---|
| `backend/app/services/role_experience.py` | v2 keys + validation (`VALID_ASSISTANT_MODES`, `VALID_HOMEPAGE_LAYOUTS`, `_V2_DEFAULTS`); **executive** config keyed `super_admin`; `resolve_config` fills v2 defaults, builds `homepage`, sets `version:2`, and **strips `prompt_fragment`** | Backend fully describes the experience; security hardening; executive experience |
| `backend/app/routes/experience.py` | docstring/contract note (behavior via `resolve_config`) | v2 delivery + security intent |
| `backend/tests/test_role_experience.py` | executive-experience test, v2-shape test, prompt-fragment-absence regression guard; updated the now-changed super_admin assertions | Contract + security coverage |
| `frontend/src/contexts/ExperienceContext.tsx` | v2 types (`AssistantMode`, `QuickAction`, `Capabilities`, `AiContext`, `HomepageSpec`); dropped `prompt_fragment` from `PersonaPack` | Client contract mirrors the payload (seam Atharva owns; Yash renders) |
| `frontend/src/components/copilot/registry.tsx` | **new** open widget registry | Extensible, forward-compatible homepage |
| `frontend/src/app/today/page.tsx` | consume the registry; read `homepage.zones` (v1 fallback); new `quick_actions` widget + `briefing_hero` alias | Open widget system; executive Q4 zone |
| `frontend/src/components/CommandPalette.tsx` | nav + quick actions from the Experience API, unioned with full role-accessible routes; fallback preserved | Config-driven palette without losing reachability |
| `frontend/src/components/ChatBot.tsx` | chat/voice gates AND `capabilities` (narrow-only) | Config-aware, server still authorizes |
| `frontend/src/components/AIProvider.tsx` | honor `assistant_mode` (`hidden` removes shell; `panel`/`copilot` render panel) | Assistant mode wired, no redesign yet |
| `frontend/src/locales/nav.ts` | +5 executive nav tKeys (EN+AR) | Sidebar renders `t(tKey)`; append rule (Yash steward) |

**Executive experience (super_admin):** home `/today`; `assistant_mode:copilot`;
nav = Overview · Executive Briefing · Business Health · Decisions · Growth · Sage
Copilot; the rest reachable by URL and ⌘K (nothing deleted). All six nav icons
already existed in `NAV_ICONS`, so `config/nav.tsx` was **not** touched.

---

## 5. Dependency graph (Phase 1 + planned)

```
routes/experience.py → role_experience.resolve_config                (Phase 1)
frontend today/page → copilot/registry ← (Phase 2/3 feed widgets)     (Phase 1)
CommandPalette / AIProvider / ChatBot → ExperienceContext             (Phase 1)
routes/copilot.py → sage_copilot → {briefing, decision_center, roi,
                                    forecast_service*, redis_client}   (Phase 2)
rag/retriever → rag/registry → rag/base                               (Phase 5)
```
*`forecast_service` is Krishna's contract seam, consumed via its existing public
API exactly as `briefing.py` already does. No cycles; `sage_copilot` is mid-tier
like `briefing`.

---

## 6. Risk analysis

| Risk | Mitigation |
|---|---|
| v2 payload breaks Yash's rendering | `version` field; all v1 keys preserved; `homepage.zones` mirrors `zones`; fail-open path untouched; `tsc` clean |
| Removing `prompt_fragment` breaks ChatBot | Verified only `persona.title` is used client-side; type dropped; `tsc` clean |
| super_admin loses the full sidebar | Curated 6-item nav is intended; every route stays reachable via ⌘K (full list unioned) + direct URL; `/settings` always pinned; reversible by reverting one config record |
| `capabilities` regresses voice for a role | Gate is `roleCheck && (cap ?? true)` — narrow-only, so current allow-sets are preserved exactly |
| Feed hallucination (Phase 2) | Proactive path is LLM-free by construction |
| Scope creep into other owners' files | Only sanctioned appends touched (`locales/nav.ts`); `config/nav.tsx` untouched; interface requests deferred (§9) |

---

## 7. Incremental roadmap

- **Phase 1 (done):** Experience API v2 + executive config + open widget registry
  + config-driven palette + assistant_mode wiring + prompt-fragment strip.
- **Phase 2:** `sage_copilot` feed service + `/api/ai/copilot/feed` + Redis cache
  + pure `build_feed` tests. Feed widgets (`business_health`, `risks`,
  `opportunities`, `recommendations`) register into the registry.
- **Phase 3:** enrich operational role configs (store/regional/procurement) with
  `quick_actions`, `ai_context`, feed zones; ExperienceContext consumers use them.
- **Phase 4:** copilot **shell** — `assistant_mode:copilot` renders the dedicated
  Sage surface (feed + embedded chat), retiring the floating pill for that mode.
- **Phase 5:** RAG interfaces (`rag/base`, `rag/registry`) + presentational
  role-leak cleanup (pages read `capabilities` instead of `hasRole` where the
  check is cosmetic).
- **Phase 6+ (coordinated/deferred):** scheduler push briefings (Krishna),
  new RBAC roles (`ceo`/`employee`), E3-3 store-health score into
  `business_health`, hosted-LLM tier (E7-3), ingestion + pgvector RAG, autonomy L2.

---

## 8. Migration, testing, rollback

- **Migration:** none — config-as-data only through Phase 3; Redis cache in
  Phase 2. Behavior migrates one role record at a time (`_default` never changes).
- **Testing:** pure builders unit-tested (mirroring `test_briefing`/
  `test_decision_center`); `test_role_experience` guards the v2 contract + the
  prompt-fragment regression; RBAC feed-scope test in the `test_ai_rbac` style
  (Phase 2); frontend `tsc --noEmit` + `next build`; live check with the three
  demo logins (one payload, three experiences); golden numbers untouched.
- **Rollback:** revert the config record (or set `assistant_mode:"panel"`); the
  client fails open to legacy UI; the feed endpoint (Phase 2) is additive and
  unused by anything else, so it can be dark-launched or abandoned harmlessly.

---

## 9. Interface requests (other owners — documented, not implemented)

**Krishna (backend platform / auth / DB):**
1. A `ceo` and `employee` value in the `user_role` enum + seed users, when we want
   true executive/employee roles rather than the `super_admin` mapping. The
   executive config already exists and can be re-keyed to `ceo` in one line.
2. A config-flagged **lifespan scheduler slot** (Phase 6) for 07:00 Asia/Dubai
   push briefings. `/api/briefing/print` is the ready email body; only the
   scheduler/SMTP wiring is needed. No new `sage_*` views required for Phases 1–4.

**Yash (frontend design system / shell):**
1. Optional dedicated icons for the executive nav (e.g. a Sparkles "Sage" and a
   heart-pulse "Business Health") added to `NAV_ICONS` in `config/nav.tsx`. Phase 1
   reuses existing icons (`LayoutDashboard/Sunrise/TrendingUp/Scale/BarChart3/
   Lightbulb`) to avoid touching that file.
2. Review of the copilot surfaces (Phase 4) for design-system consistency — they
   build exclusively on `components/ui`.
3. Longer term: Sidebar nav-manifest **section grouping** if we group nav; the
   payload stays back-compatible until then.

---

## 10. Future RAG integration plan (summary)

Now (Phase 5): protocol + registry + `permissions` on `Chunk`. Then, in order:
(1) ingestion pipeline (upload → chunk → tenant-scoped `documents` rows, audited);
(2) pgvector `embedding` column + local Ollama embedder (additive migration) with
FTS fallback; (3) document ACLs enforced in the retrieval hook (RBAC-aware
retrieval); (4) new sources (policies/SOPs/reports) as registry entries;
(5) citations + confidence already flow via `RagAnswer` → sage3 finaliser →
ChatBot meta UI. No vector server unless pgvector proves insufficient — per the
sage3 master prompt's own constraint.
