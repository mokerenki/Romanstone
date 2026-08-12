// frontend/tailwind.config.ts

import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        synthai: {
          background: '#ffffff',
          surface: '#f7f7f8',
          'surface-light': '#f0f0f1',
          'surface-hover': '#e8e8ea',
          border: '#e4e4e7',
          text: '#1a1a1e',
          'text-secondary': '#4a4a50',
          'text-muted': '#8a8a90',
        },
        text: {
          primary: '#1a1a1e',
          secondary: '#4a4a50',
          muted: '#8a8a90',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(135deg, #2563eb, #7c3aed)',
        'brand-gradient-subtle': 'linear-gradient(135deg, rgba(37,99,235,0.08), rgba(124,58,237,0.08))',
      },
      boxShadow: {
        'card': '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.08)',
      },
    },
  },
  plugins: [],
};

export default config;