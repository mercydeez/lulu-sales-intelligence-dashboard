# Brand assets

Single home for the brand mark so logo files aren't scattered across the app.
The mark is an ascending growth-bar chart fused into a bold **R**. The product
name is **"Retail Intelligence"** — always sourced from `src/lib/brand.ts`
(`PRODUCT_NAME`), never hardcoded next to the mark.

> History: the "RetailIQ" wordmark lockups (component + SVGs) were removed in
> the July 2026 feature audit — that name lost the brand reconciliation, and a
> drop-in component rendering the wrong product name was a shipping hazard.
> Recover from git history if a wordmark lockup is ever commissioned for the
> real name.

## Files

| File | Use |
|---|---|
| `retailiq-icon.svg` | The mark alone (navy) — vector source. App icon, square contexts. (Legacy filename; the mark itself is name-neutral.) |
| `favicon.svg` | The mark, tuned for tabs; wired as the primary favicon in `app/layout.tsx`. |
| `favicon-16/32.png`, `apple-touch-icon.png`, `favicon.ico` | Raster fallbacks — **generated**, see below. |

## In React (preferred — no scattered `<img>` tags)

```tsx
import { BrandIcon } from '@/components/branding/BrandIcon';

<BrandIcon size={24} className="text-teal-700" /> // raw mark, any color
<BrandIcon size={20} decorative />                // next to a text label
```

Pair the mark with the name from `@/lib/brand` (`PRODUCT_NAME`) where a lockup
is needed — see `shell/Sidebar.tsx` / `shell/DomainRail.tsx` for live examples.

## Regenerating the raster fallbacks

The PNG/ICO are derived from `favicon.svg`. They are not committed as a build
step (keeps the deploy image free of native deps):

```bash
cd frontend
npm i -D sharp png-to-ico
node scripts/branding/generate-rasters.mjs
```

## Swapping in official artwork

Replace the `.svg` files here (keep the same filenames + `viewBox`) and re-run
the raster script. `BrandIcon.tsx` inlines the mark geometry — if you change
the mark, update the paths there too so the component and files stay in sync.
