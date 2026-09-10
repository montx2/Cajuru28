import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F1F4F2",
        surface: "#FFFFFF",
        ink: "#131C19",
        "ink-muted": "#5B6B65",
        "ink-faint": "#8CA098",
        accent: "#1F6F54",
        "accent-deep": "#144E3B",
        "accent-bright": "#2FA37A",
        "accent-soft": "#E3EFE8",
        line: "#DCE3DF",
        warn: "#B8842B",
        "warn-soft": "#F6ECD8",
        danger: "#B5432E",
        "danger-soft": "#F6E3DD",
        info: "#2F6FED",
        "info-soft": "#E3EBFD",
        sidebar: "#0B1411",
        "sidebar-hover": "#152420",
        "sidebar-line": "#1E2E28",
        gold: "#C9A227",
      },
      fontFamily: {
        sans: ["var(--font-public-sans)", "system-ui", "sans-serif"],
        serif: ["var(--font-source-serif)", "Georgia", "serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        DEFAULT: "8px",
        card: "14px",
        pill: "999px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(19,28,25,.06), 0 6px 20px -8px rgba(19,28,25,.12)",
        pop: "0 12px 40px -8px rgba(19,28,25,.25)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-in-right": {
          from: { opacity: "0", transform: "translateX(32px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
      },
      animation: {
        "fade-up": "fade-up .45s ease both",
        "fade-in": "fade-in .25s ease both",
        "slide-in-right": "slide-in-right .3s ease both",
      },
    },
  },
  plugins: [],
};

export default config;
