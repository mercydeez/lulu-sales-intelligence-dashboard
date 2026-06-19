/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
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
        // Warm-neutral surfaces + neutral ink text (no more purple ink).
        canvas: '#fafaf8',
        surface: {
          DEFAULT: '#ffffff',
          1: '#ffffff',
          2: '#f4f4f0',
          3: '#eaeae4',
        },
        ink: {
          DEFAULT: '#1a1d21',
          soft: '#4b5258',
          muted: '#5f6660', // AA on white (>=4.5:1)
        },
        line: '#e6e6e0', // default hairline border
        // Semantic signals — color only ever means meaning, never decoration.
        signal: { up: '#0f8f73', down: '#c8451f' },
        alert: { critical: '#dc2626', warn: '#d97706', info: '#2563eb' },
        live: '#16a34a',
      },
      boxShadow: {
        // Calm, neutral elevation — borders do most of the work now.
        sunset: '0 1px 2px rgba(20, 29, 33, 0.06)',
        soft: '0 4px 12px rgba(20, 29, 33, 0.10)',
      },
      backgroundImage: {
        // Tailwind utility companion to the plain `.sunset-gradient` class in
        // globals.css — same stops, for components that need `bg-` composition.
        'sunset-gradient': 'linear-gradient(135deg, #0f766e 0%, #0d7d68 100%)',
      },
    },
  },
  plugins: [],
}
