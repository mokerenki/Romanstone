import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        aether: {
          50: '#f0f4ff',
          500: '#3b82f6',
          900: '#1e3a5f',
        }
      }
    },
  },
  plugins: [],
};

export default config;