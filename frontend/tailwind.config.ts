import type { Config } from "tailwindcss";

/** Grafite & Menta: tokens semânticos, tipografia de dados e geometria
 * compartilhada entre botões, campos, cartões e camadas. */
const token = (nome: string) => `rgb(var(--${nome}-rgb) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    // Escala legível para operação contínua, sem rótulos abaixo de 12 px.
    fontSize: {
      // 12px é o piso: nenhum texto do produto desce abaixo disso (WCAG/legibilidade).
      // `2xs` mantém entrelinha curta para caber em kbd, badge e rótulo de eixo.
      "2xs": ["12px", "16px"],
      xs: ["12px", "18px"],
      sm: ["14px", "22px"],
      base: ["14px", "22px"],
      md: ["16px", "24px"],
      lg: ["20px", "28px"],
      xl: ["28px", "36px"],
      "2xl": ["36px", "44px"],
      // Os dois degraus de display existem para a capa do login, a única tela
      // do produto que fala antes de o usuário entrar. Fora dela, `2xl` é o teto.
      "3xl": ["42px", "48px"],
      "4xl": ["54px", "62px"],
    },
    extend: {
      colors: {
        fundo: token("fundo"),
        "fundo-afundado": token("fundo-afundado"),
        superficie: token("superficie"),
        "superficie-alta": token("superficie-alta"),
        "tinta-forte": token("tinta-forte"),
        tinta: token("tinta"),
        "tinta-suave": token("tinta-suave"),
        "tinta-fraca": token("tinta-fraca"),
        traco: token("traco"),
        "traco-forte": token("traco-forte"),
        "borda-controle": token("borda-controle"),
        acento: token("acento"),
        "acento-escuro": token("acento-escuro"),
        "acento-tenue": token("acento-tenue"),
        "acento-borda": token("acento-borda"),
        "acento-contraste": token("acento-contraste"),
        ok: token("ok"),
        "ok-tenue": token("ok-tenue"),
        espera: token("espera"),
        "espera-contraste": token("espera-contraste"),
        "espera-tenue": token("espera-tenue"),
        erro: token("erro"),
        "erro-contraste": token("erro-contraste"),
        "erro-tenue": token("erro-tenue"),
        info: token("info"),
        "info-tenue": token("info-tenue"),
        neutro: token("neutro"),
        "neutro-tenue": token("neutro-tenue"),
        destrutivo: token("destrutivo"),
        "destrutivo-hover": token("destrutivo-hover"),
        "destrutivo-contraste": token("destrutivo-contraste"),
        grafite: token("grafite"),
        "grafite-alta": token("grafite-alta"),
        "grafite-hover": token("grafite-hover"),
        "grafite-traco": token("grafite-traco"),
        "sobre-grafite": token("sobre-grafite"),
        foco: "var(--foco)",
      },
      borderColor: { DEFAULT: token("traco") },
      // Placeholder é texto e responde a 1.4.3: `tinta-suave` (5,5:1), nunca
      // `tinta-fraca` — esta fica restrita a desabilitado e ornamento.
      placeholderColor: { DEFAULT: token("tinta-suave") },
      fontFamily: {
        sans: ["var(--fonte-sans)", "system-ui", "sans-serif"],
        mono: ["var(--fonte-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        none: "0",
        sm: "4px",
        DEFAULT: "8px",
        md: "8px",
        lg: "10px",
        xl: "12px",
        "2xl": "16px",
        "3xl": "20px",
        full: "999px",
        badge: "6px",
        controle: "8px",
        cartao: "12px",
        camada: "16px",
      },
      boxShadow: {
        none: "none",
        sm: "none",
        DEFAULT: "none",
        md: "none",
        lg: "none",
        xl: "none",
        "2xl": "none",
        inner: "none",
        cartao: "var(--sombra-cartao)",
        nivel1: "var(--sombra-1)",
        nivel2: "var(--sombra-2)",
      },
      fontWeight: {
        thin: "400",
        extralight: "400",
        light: "400",
        normal: "400",
        medium: "500",
        semibold: "600",
        bold: "600",
        extrabold: "600",
        black: "600",
      },
      maxWidth: {
        conteudo: "1600px",
        leitura: "72ch",
        formulario: "560px",
        painel: "min(620px, 92vw)",
      },
      width: { "max-painel": "min(620px, 100vw)" },
      zIndex: {
        cabecalho: "30",
        camada: "40",
        overlay: "60",
        modal: "70",
        flutuante: "75",
        aviso: "80",
        pulo: "90",
      },
      transitionDuration: {
        75: "120ms",
        100: "120ms",
        150: "120ms",
        200: "180ms",
        300: "240ms",
        500: "240ms",
        700: "240ms",
        1000: "240ms",
        120: "120ms",
        180: "180ms",
        240: "240ms",
      },
      transitionTimingFunction: {
        produto: "cubic-bezier(.2, 0, 0, 1)",
        DEFAULT: "cubic-bezier(.2, 0, 0, 1)",
      },
      keyframes: {
        // Único movimento contínuo do produto: execução em andamento.
        pulso: { "0%, 100%": { opacity: "1" }, "50%": { opacity: ".45" } },
        brilho: { "0%": { opacity: ".5" }, "50%": { opacity: ".85" }, "100%": { opacity: ".5" } },
        // Camadas (popover, modal, drawer, toast) — nunca conteúdo de página.
        entrar: { from: { opacity: "0" }, to: { opacity: "1" } },
        subir: {
          from: { opacity: "0", transform: "translateY(4px) scale(.99)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        deslizar: {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        progresso: {
          from: { transform: "translateX(-100%)" },
          to: { transform: "translateX(300%)" },
        },
      },
      animation: {
        pulso: "pulso 2s cubic-bezier(.2,0,0,1) infinite",
        brilho: "brilho 1.6s cubic-bezier(.2,0,0,1) infinite",
        entrar: "entrar 180ms cubic-bezier(.2,0,0,1) both",
        subir: "subir 180ms cubic-bezier(.2,0,0,1) both",
        deslizar: "deslizar 240ms cubic-bezier(.2,0,0,1) both",
        progresso: "progresso 1.2s cubic-bezier(.4,0,.6,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
