# RetailIQ brand assets

Single home for the brand mark so logo files aren't scattered across the app.
The mark is an ascending growth-bar chart fused into a bold **R**; the wordmark
is **Retail** (navy `#17284B`) + **IQ** (blue `#2563EB`).

## Files

| File | Use |
|---|---|
| `retailiq-icon.svg` | The mark alone (navy). App icon, square contexts. |
| `retailiq-logo.svg` | Full lockup — mark + "RetailIQ" wordmark, for light backgrounds. |
| `retailiq-logo-dark.svg` | Lockup for dark/navy backgrounds (white mark, blue "IQ"). |
| `retailiq-logo-mono.svg` | Single-color lockup (`currentColor`) — print, watermarks, one-ink. |
| `favicon.svg` | The mark, tuned for tabs; wired as the primary favicon in `app/layout.tsx`. |
| `favicon-16/32.png`, `apple-touch-icon.png`, `favicon.ico` | Raster fallbacks — **generated**, see below. |

## In React (preferred — no scattered `<img>` tags)

```tsx
import { Logo } from '@/components/branding/Logo';
import { BrandIcon } from '@/components/branding/BrandIcon';

<Logo />                         // navy + blue, auto-flips to white in dark mode
<Logo variant="dark" size={40}/> // force white + blue (on colored backgrounds)
<Logo iconOnly />                // mark only
<BrandIcon size={24} className="text-teal-700" /> // raw mark, any color
```

The wordmark renders in the app font (Manrope), so it stays crisp at any size with
no font embedding. The SVG files use a font-family stack; for pixel-locked print,
open a lockup in a vector editor and "convert text to outlines" with the licensed
display font.

## Regenerating the raster fallbacks

The PNG/ICO are derived from `favicon.svg`. They are not committed as a build
step (keeps the deploy image free of native deps):

```bash
cd frontend
npm i -D sharp png-to-ico
node scripts/branding/generate-rasters.mjs
```

## Swapping in official artwork

Replace the `.svg` files here (keep the same filenames + `viewBox`) and re-run the
raster script. `BrandIcon.tsx` inlines the mark geometry — if you change the mark,
update the paths there too so the component and files stay in sync.

## Note on palette

This mark is navy/blue per the supplied artwork. The product UI currently uses a
teal accent (`--brand: #0f766e`) and the product name string is "Retail
Intelligence". Reconcile naming/palette before a full rollout across the shell
(see the `Logo`/`BrandIcon` components, ready to drop in).
