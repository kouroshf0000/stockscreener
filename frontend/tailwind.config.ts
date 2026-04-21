import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#0B3D91", accent: "#EEF2FF" },
      },
    },
  },
  plugins: [],
};

export default config;
