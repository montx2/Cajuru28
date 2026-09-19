import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

/* Self-hosted de propósito: o build não depende de rede (Docker offline) e
   nenhum @import de fonte bloqueia o primeiro render. Veja fontes/LEIA-ME.md. */
const inter = localFont({
  src: "../fontes/inter-latin-wght-normal.woff2",
  variable: "--fonte-sans",
  display: "swap",
  weight: "100 900",
  style: "normal",
  adjustFontFallback: "Arial",
  fallback: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
});

const jetbrainsMono = localFont({
  src: "../fontes/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--fonte-mono",
  display: "swap",
  weight: "100 800",
  style: "normal",
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
});

export const metadata: Metadata = {
  title: { default: "NotasFlow", template: "%s · NotasFlow" },
  description: "Captura, validação e fechamento de documentos fiscais eletrônicos.",
  applicationName: "NotasFlow",
  icons: { icon: "/icone.png" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1513" },
  ],
};

/* Aplicado antes da primeira pintura: nada de flash branco no tema escuro.
   A sessão vive em cookie HttpOnly — aqui não há token, só preferência visual. */
const scriptTema = `(function(){try{var k="notasflow:tema";var t=localStorage.getItem(k);var m=window.matchMedia("(prefers-color-scheme: dark)");var aplicar=function(){var escuro=t==="escuro"||((t===null||t==="sistema")&&m.matches);document.documentElement.dataset.tema=escuro?"escuro":"claro";};aplicar();m.addEventListener("change",aplicar);}catch(e){document.documentElement.dataset.tema="claro";}})()`;

export default function Raiz({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${jetbrainsMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: scriptTema }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
