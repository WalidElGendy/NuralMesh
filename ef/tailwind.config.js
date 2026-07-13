/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Warm paper ground — keeps the institutional, document-like feel.
        paper: { DEFAULT: "#FBFAF9", raised: "#FFFFFF", sunk: "#F2F2F6" },
        line: { DEFAULT: "#E2E3EC", strong: "#CFD1DF" },

        // Environment Fund navy. This is the primary brand ramp.
        // NOTE: the token is still named `forest` so the existing class names across the
        // app resolve without a sweeping rename — the *values* are now the Fund's navy.
        // `navy` is the canonical alias to use in new code.
        forest: {
          50: "#F0F1F8",
          100: "#DCDFEF",
          200: "#B6BCDC",
          500: "#4A55A2",
          600: "#3A4590",
          700: "#2E3A87",
          800: "#26307A",
          900: "#1B2360",
        },
        navy: {
          50: "#F0F1F8",
          100: "#DCDFEF",
          200: "#B6BCDC",
          500: "#4A55A2",
          600: "#3A4590",
          700: "#2E3A87",
          800: "#26307A",
          900: "#1B2360",
        },

        // Green is now reserved for one meaning only: the imagery agreed.
        // Verified milestones, released tranches, healthy status. Nothing else.
        verify: {
          50: "#EDF7F1",
          100: "#D3EDDE",
          500: "#3D9970",
          600: "#2F7D5B",
          700: "#246349",
        },

        // The map stays a dark window into the field.
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
        card: "0 1px 2px rgba(27,35,96,0.04), 0 4px 16px -4px rgba(27,35,96,0.07)",
        lift: "0 2px 4px rgba(27,35,96,0.05), 0 12px 32px -8px rgba(27,35,96,0.14)",
      },
      borderRadius: { xl: "0.875rem", "2xl": "1.125rem" },
    },
  },
  plugins: [],
};
