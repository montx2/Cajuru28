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
        bg: "#F2F5F3",
        "bg-deep": "#E9EEEB",
        surface: "#FCFDFC",
        "surface-2": "#F7F9F8",

        ink: "#16201C",
        "ink-muted": "#65716B",
        "ink-2": "#65716B",
        "ink-faint": "#98A29D",

        accent: "#197154",
        "accent-deep": "#10563E",
        "accent-bright": "#5BC594",
        "accent-soft": "#E4F3EC",
        "accent-glow": "#BCEBD4",

        line: "#DEE6E1",
        "line-strong": "#CBD7D0",

        warn: "#A86F12",
        "warn-soft": "#FBF0D9",
        danger: "#C04434",
        "danger-soft": "#FBE7E3",
        info: "#3867C8",
        "info-soft": "#E8EEFD",

        sidebar: "#111A17",
        "sidebar-2": "#18241F",
        "sidebar-hover": "#22312B",
        "sidebar-line": "#293A32",
        gold: "#D5B451",
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
        DEFAULT: "10px",
        card: "16px",
        "card-lg": "22px",
        pill: "999px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(18, 31, 25, .025), 0 12px 32px -22px rgba(18, 31, 25, .24)",
        "card-hover": "0 2px 5px rgba(18, 31, 25, .04), 0 20px 42px -22px rgba(18, 31, 25, .28)",
        pop: "0 24px 64px -24px rgba(12, 22, 17, .38)",
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
