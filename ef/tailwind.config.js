/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // EFund: calm, institutional, trustworthy. Warm paper + deep evergreen.
        paper: { DEFAULT: "#FBFAF8", raised: "#FFFFFF", sunk: "#F4F2ED" },
        line: { DEFAULT: "#E7E3DB", strong: "#D6D1C6" },
        forest: {
          50: "#F0F5F1",
          100: "#DCE8DE",
          200: "#B9D1BE",
          500: "#3D7A52",
          600: "#2F6141",
          700: "#254E35",
          800: "#1B3A27",
          900: "#12271A",
        },
        // The map is a dark window into the field — deliberate contrast with the paper UI.
        field: { 900: "#0B0F0D", 800: "#131A16", 700: "#1C251F", line: "#2A352D" },
        signal: "#3FD68C",
        sand: "#C9A227",
        clay: "#B4472E",
      },
      fontFamily: {
        display: ['"Instrument Serif"', "Georgia", "serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(18,39,26,0.04), 0 4px 16px -4px rgba(18,39,26,0.06)",
        lift: "0 2px 4px rgba(18,39,26,0.04), 0 12px 32px -8px rgba(18,39,26,0.12)",
      },
      borderRadius: { xl: "0.875rem", "2xl": "1.125rem" },
    },
  },
  plugins: [],
};
