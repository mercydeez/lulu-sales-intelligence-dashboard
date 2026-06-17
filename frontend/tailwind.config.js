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
      },
      colors: {
        // Sunset Pop palette — playful, warm, professional
        coral: {
          50: '#fff1ef',
          100: '#ffe1dc',
          200: '#ffc7bd',
          300: '#ffa194',
          400: '#ff7a68',
          500: '#ff6b5c', // primary
          600: '#ed4b39',
          700: '#c8351f',
          800: '#a52e1d',
          900: '#882c1f',
        },
        teal: {
          50: '#effdfa',
          100: '#cbfbf1',
          200: '#97f5e4',
          300: '#5ce9d4',
          400: '#2dd4bf', // tertiary
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
          800: '#115e59',
          900: '#134e4a',
        },
        // `violet` and `amber` ship with Tailwind; keep a primary alias
        primary: {
          50: '#fff1ef',
          100: '#ffe1dc',
          200: '#ffc7bd',
          300: '#ffa194',
          400: '#ff7a68',
          500: '#ff6b5c',
          600: '#ed4b39',
          700: '#c8351f',
          800: '#a52e1d',
          900: '#882c1f',
        },
        // Warm light surfaces + deep ink text
        canvas: '#fdf6f3',
        surface: '#ffffff',
        ink: {
          DEFAULT: '#1e1b2e',
          soft: '#4b4763',
          muted: '#6b6680', // darkened for WCAG AA (5.47:1 on white) — 3.7
        },
      },
      boxShadow: {
        sunset: '0 18px 40px -12px rgba(255, 107, 92, 0.45)',
        'sunset-violet': '0 18px 40px -12px rgba(139, 92, 246, 0.4)',
        soft: '0 10px 30px -12px rgba(30, 27, 46, 0.18)',
      },
      backgroundImage: {
        // Deepened to 700-level stops so white text clears WCAG AA (>=5:1) — 3.7
        'sunset-gradient': 'linear-gradient(135deg, #c8351f 0%, #6d28d9 100%)',
        'sunset-warm': 'linear-gradient(135deg, #c8351f 0%, #b45309 100%)',
        'sunset-cool': 'linear-gradient(135deg, #6d28d9 0%, #0f766e 100%)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float-slow': 'float 6s ease-in-out infinite',
        'blob': 'blob 12s ease-in-out infinite',
      },
      keyframes: {
        blob: {
          '0%, 100%': { transform: 'translate(0px, 0px) scale(1)' },
          '33%': { transform: 'translate(30px, -40px) scale(1.1)' },
          '66%': { transform: 'translate(-20px, 20px) scale(0.95)' },
        },
      },
    },
  },
  plugins: [],
}
