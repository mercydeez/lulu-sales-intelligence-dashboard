# ROUTE_MAP

Every frontend route, the API endpoints it reaches (page + imported components, resolved 2 levels deep), and each endpoint's live status from the authenticated sweep.

Legend: `ok` 200 with data · `empty` 200 but no rows · `by-design` auth/feature-gated on purpose · `needs-params` 422 without query params · `untested` POST or requires path params · `FAIL` real defect.

### `/`  — EMPTY-DATA
- `/api/alerts/summary` — ok 1219ms
- `/api/analytics/categories` — ok 501ms
- `/api/analytics/stores` — ok 167ms
- `/api/analytics/top-items` — ok 681ms
- `/api/analytics/trend` — ok 605ms
- `/api/auth/onboarding` — ok 99ms
- `/api/auth/stream-ticket` — untested
- `/api/feedback` — empty 59ms
- `/api/findings` — ok 53ms
- `/api/findings/` — untested
- `/api/findings/summary` — ok 48ms
- `/api/inventory/expiry-summary` — ok 62ms
- `/api/inventory/reorder-suggestions` — ok 358ms
- `/api/inventory/summary` — ok 53ms
- `/api/kpis` — ok 66ms
- `/api/kpis/projection` — ok 62ms
- `/api/procurement/approvals` — empty 50ms
- `/api/sales/` — ok 96ms
- `/api/sales/aggregated` — ok 166ms
- `/api/sales/items` — ok 53ms
- `/api/sales/metrics` — ok 89ms
- `/api/sales/predictions` — ok 35ms
- `/api/sales/predictions/backtest` — ok 40ms
- `/api/sales/stores` — ok 57ms
- `/api/security/events` — ok 64ms
- `/api/security/kpi` — ok 70ms
- `/api/security/summary` — ok 71ms
- `/stream/latest` — ok 133ms
- `/stream/sales` — by-design 28ms

### `/accept-invite`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/action-drafts`  — EMPTY-DATA
- `/api/action-drafts` — empty 282ms
- `/api/action-drafts/` — untested

### `/admin`  — OK
- `/api/admin/activity` — ok 395ms
- `/api/admin/dashboard` — ok 198ms
- `/api/admin/stores` — ok 194ms
- `/api/admin/users` — ok 107ms

### `/admin/tenants`  — OK
- `/api/tenants` — ok 88ms
- `/api/tenants/` — untested
- `/api/tenants/metrics` — ok 73ms

### `/alerts`  — EMPTY-DATA
- `/api/alerts/` — untested
- `/api/alerts/list` — ok 576ms
- `/api/alerts/my-tasks` — empty 90ms
- `/api/alerts/recent` — ok 1339ms
- `/api/alerts/rules` — ok 38ms
- `/api/alerts/stats` — ok 91ms
- `/api/alerts/summary` — ok 1219ms
- `/api/auth/stream-ticket` — untested
- `/stream/alerts` — by-design 38ms
- `/stream/sales` — by-design 28ms

### `/analytics`  — OK
- `/api/analytics/categories` — ok 501ms
- `/api/analytics/stores` — ok 167ms
- `/api/analytics/top-items` — ok 681ms
- `/api/analytics/trend` — ok 605ms
- `/api/findings` — ok 53ms
- `/api/findings/` — untested
- `/api/findings/summary` — ok 48ms
- `/api/kpis` — ok 66ms
- `/api/kpis/projection` — ok 62ms
- `/api/sales/` — ok 96ms
- `/api/sales/aggregated` — ok 166ms
- `/api/sales/items` — ok 53ms
- `/api/sales/metrics` — ok 89ms
- `/api/sales/predictions` — ok 35ms
- `/api/sales/predictions/backtest` — ok 40ms
- `/api/sales/stores` — ok 57ms
- `/api/security/events` — ok 64ms
- `/api/security/kpi` — ok 70ms
- `/api/security/summary` — ok 71ms

### `/approvals`  — EMPTY-DATA
- `/api/procurement/approvals` — empty 50ms
- `/api/procurement/purchase-orders/` — untested

### `/audit`  — OK
- `/api/security/events` — ok 64ms
- `/api/security/events/export` — ok 80ms

### `/briefing`  — OK
- `/api/briefing` — ok 641ms
- `/api/briefing/print` — ok 622ms

### `/copilot`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/data-sources`  — OK
- `/api/data-sources` — ok 23ms
- `/api/data-sources/` — untested
- `/api/data-sources/test` — untested

### `/decisions`  — OK
- `/api/action-drafts/from-finding/` — untested
- `/api/analytics/categories` — ok 501ms
- `/api/analytics/stores` — ok 167ms
- `/api/analytics/top-items` — ok 681ms
- `/api/analytics/trend` — ok 605ms
- `/api/decisions` — ok 83ms
- `/api/decisions/triage` — ok 113ms
- `/api/findings` — ok 53ms
- `/api/findings/` — untested
- `/api/findings/summary` — ok 48ms
- `/api/kpis` — ok 66ms
- `/api/kpis/projection` — ok 62ms
- `/api/sales/` — ok 96ms
- `/api/sales/aggregated` — ok 166ms
- `/api/sales/items` — ok 53ms
- `/api/sales/metrics` — ok 89ms
- `/api/sales/predictions` — ok 35ms
- `/api/sales/predictions/backtest` — ok 40ms
- `/api/sales/stores` — ok 57ms
- `/api/security/events` — ok 64ms
- `/api/security/kpi` — ok 70ms
- `/api/security/summary` — ok 71ms

### `/dev/components`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/developers`  — EMPTY-DATA
- `/api/api-keys` — ok 127ms
- `/api/api-keys/` — untested
- `/api/tenants/usage` — ok 58ms
- `/api/tenants/usage/period` — empty 62ms
- `/api/webhooks` — empty 61ms
- `/api/webhooks/` — untested
- `/api/webhooks/events` — ok 55ms
- `/api/webhooks/test` — untested

### `/employees`  — OK
- `/api/employees/employees` — ok 264ms
- `/api/employees/employees/analytics/by-role` — ok 58ms
- `/api/employees/employees/analytics/summary` — ok 200ms

### `/flywheel`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/approvals`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/budget`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/campaigns/[id]`  — EMPTY-DATA
- `/api/auth/stream-ticket` — untested
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms
- `/stream/flywheel` — by-design 37ms
- `/stream/sales` — by-design 28ms

### `/flywheel/cannibalization`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/coalition`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/customers`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/decisions/[id]`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/governance`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/holdout`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/incrementality`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/models`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/models/shadow`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/seasonality`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/studio`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/flywheel/trade`  — EMPTY-DATA
- `/api/flywheel/approvals` — empty 46ms
- `/api/flywheel/approvals/` — untested
- `/api/flywheel/approvals/steps/` — untested
- `/api/flywheel/budget` — ok 645ms
- `/api/flywheel/campaigns` — empty 748ms
- `/api/flywheel/campaigns/` — untested
- `/api/flywheel/churn/score` — untested
- `/api/flywheel/customers` — ok 328ms
- `/api/flywheel/customers/` — untested
- `/api/flywheel/decisioning/evaluate` — untested
- `/api/flywheel/decisioning/redeem` — untested
- `/api/flywheel/decisions/` — untested
- `/api/flywheel/features/build` — untested
- `/api/flywheel/governance` — ok 266ms
- `/api/flywheel/health` — ok 237ms
- `/api/flywheel/holdout` — empty 221ms
- `/api/flywheel/incrementality` — ok 83ms
- `/api/flywheel/inventory/atp` — needs-params 60ms
- `/api/flywheel/metering` — ok 44ms
- `/api/flywheel/models` — empty 50ms
- `/api/flywheel/models/shadow` — ok 48ms
- `/api/flywheel/models/shadow/score` — untested
- `/api/flywheel/outcome-pricing` — empty 64ms
- `/api/flywheel/requisitions/` — untested
- `/api/flywheel/seasonality` — ok 68ms
- `/api/flywheel/seed` — untested
- `/api/flywheel/shelf-life` — empty 63ms
- `/api/flywheel/suppliers/` — untested
- `/api/flywheel/trade` — empty 1575ms

### `/forecast-lab`  — OK
- `/api/analytics/model-metrics` — ok 43ms
- `/api/analytics/model-metrics/recompute` — untested

### `/imports`  — OK
- `/api/imports` — ok 224ms
- `/api/imports/` — untested
- `/api/imports/analyze` — untested
- `/api/imports/commit` — untested
- `/api/imports/sample/` — untested
- `/api/imports/types` — ok 79ms
- `/api/imports/validate` — untested

### `/insights`  — OK
- `/api/action-drafts/from-finding/` — untested
- `/api/analytics/categories` — ok 501ms
- `/api/analytics/stores` — ok 167ms
- `/api/analytics/top-items` — ok 681ms
- `/api/analytics/trend` — ok 605ms
- `/api/findings` — ok 53ms
- `/api/findings/` — untested
- `/api/findings/summary` — ok 48ms
- `/api/kpis` — ok 66ms
- `/api/kpis/projection` — ok 62ms
- `/api/sales/` — ok 96ms
- `/api/sales/aggregated` — ok 166ms
- `/api/sales/items` — ok 53ms
- `/api/sales/metrics` — ok 89ms
- `/api/sales/predictions` — ok 35ms
- `/api/sales/predictions/backtest` — ok 40ms
- `/api/sales/stores` — ok 57ms
- `/api/security/events` — ok 64ms
- `/api/security/kpi` — ok 70ms
- `/api/security/summary` — ok 71ms

### `/inventory`  — OK
- `/api/auth/stream-ticket` — untested
- `/api/inventory/categories` — ok 70ms
- `/api/inventory/items` — ok 86ms
- `/api/inventory/summary` — ok 53ms
- `/stream/alerts` — by-design 38ms
- `/stream/sales` — by-design 28ms

### `/login`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/methodology`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/monitoring`  — OK
- `/api/monitoring/health/detailed` — ok 89ms
- `/api/monitoring/metrics/json` — ok 36ms
- `/api/monitoring/stats` — ok 345ms

### `/operations`  — EMPTY-DATA
- `/api/auth/stream-ticket` — untested
- `/api/operations/briefing` — empty 75ms
- `/api/operations/findings/` — untested
- `/api/operations/metrics` — ok 65ms
- `/api/operations/proposals/` — untested
- `/api/operations/runs/` — untested
- `/stream/operations` — by-design 31ms
- `/stream/sales` — by-design 28ms

### `/outcome-pricing`  — OK
- `/api/outcome-pricing/invoice` — untested
- `/api/outcome-pricing/plan` — ok 50ms
- `/api/outcome-pricing/realizations` — ok 64ms
- `/api/outcome-pricing/realizations/` — untested
- `/api/outcome-pricing/statement` — ok 57ms

### `/platform-console`  — OK
- `/api/admin/dev/customizations/` — untested
- `/api/admin/dev/customizations/catalog` — ok 200ms
- `/api/tenants` — ok 88ms

### `/platform-console/bespoke`  — EMPTY-DATA
- `/api/admin/dev/bespoke` — empty 206ms
- `/api/admin/dev/bespoke/` — untested
- `/api/ai/atelier/suggest` — untested
- `/api/tenants` — ok 88ms

### `/platform-console/ops`  — OK
- `/api/admin/dev/ops/cache-flush` — untested
- `/api/admin/dev/ops/demo-reset` — untested
- `/api/admin/dev/ops/status` — ok 309ms

### `/pricing`  — OK
- `/api/billing/plans` — ok 69ms

### `/procurement`  — OK
- `/api/inventory/reorder-suggestions` — ok 358ms
- `/api/procurement/events` — ok 66ms
- `/api/procurement/purchase-orders` — ok 57ms
- `/api/procurement/purchase-orders/` — untested
- `/api/procurement/purchase-orders/generate` — untested
- `/api/procurement/suppliers` — ok 47ms

### `/procurement/po/[id]`  — OK
- `/api/procurement/events` — ok 66ms
- `/api/procurement/purchase-orders/` — untested

### `/profile`  — OK
- `/api/auth/2fa/disable` — untested
- `/api/auth/2fa/enable` — untested
- `/api/auth/2fa/setup` — untested

### `/promotions`  — OK
- `/api/promotions/active` — ok 85ms
- `/api/promotions/categories` — ok 51ms
- `/api/promotions/list` — ok 78ms
- `/api/promotions/summary` — ok 87ms

### `/reports`  — OK
- `/api/analytics/categories` — ok 501ms
- `/api/analytics/stores` — ok 167ms
- `/api/analytics/top-items` — ok 681ms
- `/api/analytics/trend` — ok 605ms
- `/api/findings` — ok 53ms
- `/api/findings/` — untested
- `/api/findings/summary` — ok 48ms
- `/api/kpis` — ok 66ms
- `/api/kpis/projection` — ok 62ms
- `/api/reports/sales` — ok 260ms
- `/api/sales/` — ok 96ms
- `/api/sales/aggregated` — ok 166ms
- `/api/sales/items` — ok 53ms
- `/api/sales/metrics` — ok 89ms
- `/api/sales/predictions` — ok 35ms
- `/api/sales/predictions/backtest` — ok 40ms
- `/api/sales/stores` — ok 57ms
- `/api/security/events` — ok 64ms
- `/api/security/kpi` — ok 70ms
- `/api/security/summary` — ok 71ms

### `/reset-password`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/role-workbench`  — EMPTY-DATA
- `/api/decisions/summary` — ok 29ms
- `/api/inventory/summary` — ok 53ms
- `/api/kpis` — ok 66ms
- `/api/procurement/approvals` — empty 50ms

### `/security`  — OK
- `/api/analytics/categories` — ok 501ms
- `/api/analytics/stores` — ok 167ms
- `/api/analytics/top-items` — ok 681ms
- `/api/analytics/trend` — ok 605ms
- `/api/auth/stream-ticket` — untested
- `/api/findings` — ok 53ms
- `/api/findings/` — untested
- `/api/findings/summary` — ok 48ms
- `/api/kpis` — ok 66ms
- `/api/kpis/projection` — ok 62ms
- `/api/sales/` — ok 96ms
- `/api/sales/aggregated` — ok 166ms
- `/api/sales/items` — ok 53ms
- `/api/sales/metrics` — ok 89ms
- `/api/sales/predictions` — ok 35ms
- `/api/sales/predictions/backtest` — ok 40ms
- `/api/sales/stores` — ok 57ms
- `/api/security/events` — ok 64ms
- `/api/security/kpi` — ok 70ms
- `/api/security/summary` — ok 71ms
- `/stream/sales` — by-design 28ms
- `/stream/security` — by-design 28ms

### `/settings`  — OK
- `/api/notifications/preferences` — ok 71ms

### `/settings/billing`  — EMPTY-DATA
- `/api/billing/invoices` — ok 60ms
- `/api/billing/invoices/` — untested
- `/api/billing/subscription` — ok 51ms
- `/api/tenants/usage` — ok 58ms
- `/api/tenants/usage/period` — empty 62ms

### `/settings/company`  — OK
- `/api/tenants/billing-profile` — ok 85ms

### `/settings/team`  — OK
- `/api/auth/invite` — untested
- `/api/team` — ok 96ms
- `/api/team/` — untested
- `/api/team/seats` — ok 105ms

### `/signup`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/status`  — OK
- `/api/monitoring/live` — ok 21ms
- `/api/monitoring/ready` — ok 77ms

### `/today`  — EMPTY-DATA
- `/api/briefing` — ok 641ms
- `/api/decisions/summary` — ok 29ms
- `/api/decisions/triage` — ok 113ms
- `/api/inventory/summary` — ok 53ms
- `/api/kpis` — ok 66ms
- `/api/procurement/approvals` — empty 50ms
- `/api/procurement/purchase-orders/` — untested

### `/trust`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/uae-insights`  — OK
- `/api/uae-intelligence/calendar` — ok 44ms
- `/api/uae-intelligence/dead-stock-by-emirate` — ok 53ms
- `/api/uae-intelligence/emirate-performance` — ok 114ms
- `/api/uae-intelligence/transfer-suggestions` — ok 62ms

### `/value`  — OK
- `/api/roi/report` — ok 317ms
- `/api/roi/summary` — ok 231ms

### `/verify-email`  — OK
- _no API calls resolved (static page or deeper indirection)_

### `/welcome`  — OK
- `/api/auth/onboarding` — ok 99ms
