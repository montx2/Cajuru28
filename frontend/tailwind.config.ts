import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F3F5F4",
        surface: "#FFFFFF",
        ink: "#16221E",
        "ink-muted": "#5B6B65",
        accent: "#1F6F54",
        "accent-soft": "#E4EFE9",
        line: "#D9DFDC",
        warn: "#B8842B",
        "warn-soft": "#F4E9D6",
        danger: "#B5432E",
        "danger-soft": "#F5E2DD",
      },
      fontFamily: {
        sans: ["var(--font-public-sans)", "system-ui", "sans-serif"],
        serif: ["var(--font-source-serif)", "Georgia", "serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        DEFAULT: "3px",
      },
    },
  },
  plugins: [],
};

export default config;
