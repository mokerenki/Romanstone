import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
          950: '#1e1b4b',
        },
        synthai: {
          background: '#0a0a16',
          surface: '#12121f',
          'surface-light': '#1a1a2e',
          'surface-hover': '#24243a',
          border: '#2a2a42',
          text: '#f0f0ff',
          'text-secondary': '#9090b0',
          'text-muted': '#606080',
        },
        // ─── BUGFIX ──────────────────────────────────────────────
        // globals.css defines --text-primary / --text-secondary /
        // --text-muted as CSS variables, and most components (Sidebar,
        // and now Chatinterface) were written assuming Tailwind
        // classes like `text-text-primary` exist -- but no `text`
        // color group was ever added here, only the differently-named
        // `synthai.text` / `synthai.text-secondary` / `synthai.text-muted`.
        // Every `text-text-primary`-style class in the app was
        // therefore compiling to nothing and silently falling back to
        // the browser default color on a dark background. Mirroring
        // the same values under a `text` key here is what actually
        // makes those classes resolve.
        text: {
          primary: '#f0f0ff',
          secondary: '#9090b0',
          muted: '#606080',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(135deg, #6366f1, #8b5cf6, #d946ef)',
        'brand-gradient-subtle': 'linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.1), rgba(217,70,239,0.1))',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'gradient': 'gradient 3s ease infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        gradient: {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
    },
  },
  plugins: [],
};

export default config;