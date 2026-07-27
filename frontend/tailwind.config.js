/** @type {import('tailwindcss').Config} */
module.exports = {
  // Theme is class-driven (html.light / html.dark, applied pre-paint in
  // layout.tsx and at runtime by ThemeContext). Most theming flows through the
  // CSS channel variables in globals.css; `dark:` variants are for edge cases.
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    // lib holds shared class maps (e.g. lib/severity.ts) — must be scanned or
    // the JIT never emits those utilities.
    './src/lib/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-manrope)', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['var(--font-plex-mono)', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        // ── Operations console palette ──────────────────────────────────────
        // Brand = deep teal-green (market-fresh, not tied to any retailer).
        // Kept the `coral`/`primary`/`teal` token NAMES so existing component
        // classes resolve, but recoloured the values toward the calm direction.
        teal: {
          50: '#e1f5ee',
          100: '#c2ebdd',
          200: '#8fd9c4',
          300: '#5dc7aa',
          400: '#2da88a',
          500: '#0f8f73',
          600: '#0d7d68', // brand mid
          700: '#0f766e', // brand (active nav, primary)
          800: '#115e59',
          900: '#134e4a',
        },
        // `primary` now points at the teal-green brand (was coral).
        primary: {
          50: '#e1f5ee',
          100: '#c2ebdd',
          200: '#8fd9c4',
          300: '#5dc7aa',
          400: '#2da88a',
          500: '#0f8f73',
          600: '#0d7d68',
          700: '#0f766e',
          800: '#115e59',
          900: '#134e4a',
        },
        // `coral` retained as a *warm signal* hue (returns / attention), used
        // sparingly — no longer the brand.
        coral: {
          50: '#fbeee7',
          100: '#f5d3c4',
          200: '#eca889',
          300: '#e08a63',
          400: '#d85a30',
          500: '#c8451f',
          600: '#a3381a',
          700: '#7e2c15',
          800: '#5c2010',
          900: '#3f160b',
        },
        // Themeable neutral tokens — driven by CSS channel variables (globals.css
        // :root / html.dark). Light values equal the old hard-coded hex, so light
        // mode is pixel-unchanged; html.dark swaps the channels.
        canvas: 'rgb(var(--c-canvas) / <alpha-value>)',
        surface: {
          DEFAULT: 'rgb(var(--c-surface) / <alpha-value>)',
          1: 'rgb(var(--c-surface-1) / <alpha-value>)',
          2: 'rgb(var(--c-surface-2) / <alpha-value>)',
          3: 'rgb(var(--c-surface-3) / <alpha-value>)',
        },
        ink: {
          DEFAULT: 'rgb(var(--c-ink) / <alpha-value>)',
          soft: 'rgb(var(--c-ink-soft) / <alpha-value>)',
          muted: 'rgb(var(--c-ink-muted) / <alpha-value>)',
        },
        line: 'rgb(var(--c-line) / <alpha-value>)', // default hairline border
        // Semantic signals — color only ever means meaning, never decoration.
        signal: { up: '#0f8f73', down: '#c8451f' },
        alert: { critical: '#dc2626', warn: '#d97706', info: '#2563eb' },
        live: '#16a34a',
        // Categorical chart/series palette — distinct, AA-contrast hues, mirrored
        // in globals.css (--series-*) and lib/chart.ts (CHART_SERIES).
        series: {
          1: '#0f766e', 2: '#6d49cf', 3: '#d97706', 4: '#c8451f',
          5: '#2563eb', 6: '#0f8f73', 7: '#db2777', 8: '#475569',
        },
      },
      boxShadow: {
        // Layered, soft elevation for a more dimensional, immersive surface.
        sunset: '0 1px 2px rgba(20, 29, 33, 0.06)',
        soft: '0 4px 12px rgba(20, 29, 33, 0.10)',
        card: '0 1px 2px rgba(20,29,33,0.04), 0 8px 24px -16px rgba(20,29,33,0.18)',
        elevated: '0 2px 6px rgba(20,29,33,0.06), 0 24px 48px -24px rgba(20,29,33,0.30)',
        'glow-teal': '0 0 0 1px rgba(15,118,110,0.18), 0 12px 32px -12px rgba(15,118,110,0.45)',
      },
      backgroundImage: {
        // Tailwind utility companions to the plain gradient classes in globals.css.
        'sunset-gradient': 'linear-gradient(135deg, #0f766e 0%, #0d8b73 55%, #14a085 100%)',
        'grad-violet': 'linear-gradient(135deg, #6d49cf 0%, #8b5cf6 100%)',
        'grad-amber': 'linear-gradient(135deg, #d97706 0%, #f59e0b 100%)',
        'grad-coral': 'linear-gradient(135deg, #c8451f 0%, #e0623a 100%)',
        'grad-blue': 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
      },
    },
  },
  plugins: [],
}
