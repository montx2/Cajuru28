import type { Config } from "tailwindcss";

/**
 * Design system NotasFlow — refeito para um padrão "equipe sênior":
 *
 * - Cores: base neutra fria (slate esverdeado) + acento esmeralda moderno,
 *   com superfícies translúcidas para glassmorphism e sombras duplas
 *   (clara/escura) para neumorphism.
 * - Tipografia: display (Clash/Satoshi via fallback), texto (Inter var) e
 *   mono (Geist Mono). Escala fluida controlada em globals.css.
 * - Raio generoso, sombras suaves em camadas, ritmo consistente.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // fundo do app (levemente esverdeado, frio) e superfícies
        bg: "#EDF1EF",
        "bg-deep": "#E3E9E6",
        surface: "#FFFFFF",
        "surface-2": "#F7FAF8",

        // tinta / texto
        ink: "#0E1613",
        "ink-muted": "#55655F",
        "ink-2": "#55655F",
        "ink-faint": "#8B9C95",

        // acento esmeralda (mais vivo e contemporâneo)
        accent: "#0F9D6B",
        "accent-deep": "#0A7A52",
        "accent-bright": "#26D08B",
        "accent-soft": "#E0F4EC",
        "accent-glow": "#5BE9B4",

        line: "#E2E9E5",
        "line-strong": "#CDD8D2",

        warn: "#B57F16",
        "warn-soft": "#FBF0D8",
        danger: "#C93B28",
        "danger-soft": "#FBE3DE",
        info: "#2563EB",
        "info-soft": "#E2EAFE",

        // sidebar — grafite profundo, quase preto esverdeado
        sidebar: "#0A100E",
        "sidebar-2": "#0E1613",
        "sidebar-hover": "#16211D",
        "sidebar-line": "#1C2A25",

        gold: "#C9A227",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        // compat: telas antigas usam font-serif para títulos
        serif: ["var(--font-display)", "var(--font-inter)", "system-ui", "sans-serif"],
      },
      letterSpacing: {
        tightest: "-0.04em",
        tighter: "-0.02em",
      },
      borderRadius: {
        DEFAULT: "10px",
        card: "18px",
        "card-lg": "24px",
        pill: "999px",
      },
      boxShadow: {
        // sombra de cartão em camadas — profundidade real, discreta
        card: "0 1px 2px rgba(14,22,19,.04), 0 8px 24px -12px rgba(14,22,19,.14)",
        "card-hover": "0 2px 6px rgba(14,22,19,.06), 0 20px 48px -16px rgba(14,22,19,.22)",
        pop: "0 16px 50px -12px rgba(14,22,19,.30)",
        // neumorphism: luz no topo-esquerda, sombra na base-direita
        neu: "6px 6px 16px rgba(14,22,19,.10), -6px -6px 16px rgba(255,255,255,.90)",
        "neu-inset":
          "inset 3px 3px 8px rgba(14,22,19,.09), inset -3px -3px 8px rgba(255,255,255,.85)",
        "neu-sm": "3px 3px 8px rgba(14,22,19,.08), -3px -3px 8px rgba(255,255,255,.85)",
        // brilho do acento (botões primários, foco)
        glow: "0 8px 24px -6px rgba(15,157,107,.45)",
        "inner-top": "inset 0 1px 0 rgba(255,255,255,.6)",
      },
      backdropBlur: {
        xs: "2px",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "scale-in": {
          from: { opacity: "0", transform: "scale(.97)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        "slide-in-right": {
          from: { opacity: "0", transform: "translateX(32px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        "glow-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
      },
      animation: {
        "fade-up": "fade-up .5s cubic-bezier(.2,.7,.2,1) both",
        "fade-in": "fade-in .3s ease both",
        "scale-in": "scale-in .22s cubic-bezier(.2,.7,.2,1) both",
        "slide-in-right": "slide-in-right .32s cubic-bezier(.2,.7,.2,1) both",
      },
    },
  },
  plugins: [],
};

export default config;
