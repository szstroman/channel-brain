import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Background layers
        bg: {
          base: "#0a0a0a",
          panel: "#0f0f0f",
          card: "#141414",
          input: "#1a1a1a",
          sidebar: "#050505",
        },
        // Borders
        border: {
          subtle: "#1a1a1a",
          default: "#1e1e1e",
          strong: "#2a2a2a",
          input: "#3a3a3a",
        },
        // Text
        fg: {
          primary: "#f5f0e8",
          secondary: "#ccc",
          muted: "#888",
          faint: "#666",
          dim: "#444",
        },
        // Mode accents (audience default; creator overrides via CSS var)
        accent: {
          audience: "#5eb8ff",
          "audience-hover": "#3a9aec",
          creator: "#d4a359",
          "creator-hover": "#c4934a",
        },
      },
      fontFamily: {
        sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
        serif: ["var(--font-playfair)", "Georgia", "serif"],
        mono: ["var(--font-dm-mono)", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
