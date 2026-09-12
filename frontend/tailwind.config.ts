import type { Config } from "tailwindcss";

/**
 * Sistema visual do NotasFlow.
 *
 * A base foi reduzida a tons frios de papel e grafite, com verde-petróleo como
 * único acento funcional. A profundidade vem de transparência e sombras muito
 * suaves — não de bordas, gradientes ou cores competindo pela atenção.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Tela clara com superfícies "papel": menos vidro decorativo e mais contraste funcional.
        bg: "#F5F7F5",
        "bg-deep": "#EDF1EE",
        surface: "#FFFFFF",
        "surface-2": "#F8FAF8",

        ink: "#17211D",
        "ink-muted": "#61706A",
        "ink-2": "#61706A",
        "ink-faint": "#8A9791",

        accent: "#147558",
        "accent-deep": "#0B513D",
        "accent-bright": "#29B783",
        "accent-soft": "#E4F5EC",
        "accent-glow": "#A9E8C8",

        line: "#DEE6E1",
        "line-strong": "#C8D5CE",

        warn: "#A86A12",
        "warn-soft": "#FFF4DD",
        danger: "#BE4437",
        "danger-soft": "#FDEAE6",
        info: "#2F6FD0",
        "info-soft": "#EAF0FE",

        sidebar: "#15201B",
        "sidebar-2": "#1D2A24",
        "sidebar-hover": "#26362E",
        "sidebar-line": "#314139",
        gold: "#D3A843",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        serif: ["var(--font-display)", "var(--font-sans)", "system-ui", "sans-serif"],
      },
      letterSpacing: {
        tightest: "-0.05em",
        tighter: "-0.025em",
      },
      borderRadius: {
        DEFAULT: "9px",
        card: "14px",
        "card-lg": "18px",
        pill: "999px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(18, 31, 25, .035), 0 8px 24px -20px rgba(18, 31, 25, .2)",
        "card-hover": "0 3px 8px rgba(18, 31, 25, .05), 0 18px 34px -20px rgba(18, 31, 25, .25)",
        pop: "0 22px 56px -24px rgba(12, 22, 17, .32)",
        neu: "8px 8px 22px rgba(51, 67, 59, .12), -8px -8px 22px rgba(255, 255, 255, .8)",
        "neu-inset": "inset 2px 2px 5px rgba(37, 52, 44, .06), inset -2px -2px 5px rgba(255, 255, 255, .72)",
        "neu-sm": "3px 3px 9px rgba(51, 67, 59, .09), -3px -3px 9px rgba(255, 255, 255, .82)",
        glow: "0 10px 24px -10px rgba(25, 113, 84, .55)",
        "inner-top": "inset 0 1px 0 rgba(255, 255, 255, .72)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "scale-in": { from: { opacity: "0", transform: "scale(.985)" }, to: { opacity: "1", transform: "scale(1)" } },
        "slide-in-right": { from: { opacity: "0", transform: "translateX(24px)" }, to: { opacity: "1", transform: "translateX(0)" } },
        shimmer: { "0%": { backgroundPosition: "-500px 0" }, "100%": { backgroundPosition: "500px 0" } },
        pulse: { "0%, 100%": { opacity: "1" }, "50%": { opacity: ".38" } },
      },
      animation: {
        "fade-up": "fade-up .42s cubic-bezier(.16, 1, .3, 1) both",
        "fade-in": "fade-in .2s ease both",
        "scale-in": "scale-in .2s cubic-bezier(.16, 1, .3, 1) both",
        "slide-in-right": "slide-in-right .28s cubic-bezier(.16, 1, .3, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
