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
  title: { default: "Fluxa", template: "%s · Fluxa" },
  description: "Captura, validação e fechamento de documentos fiscais eletrônicos.",
  applicationName: "Fluxa",
  icons: {
    icon: [
      { url: "/favicon-16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icone-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icone-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#eef1f8" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0d1c" },
  ],
};

/* Aplicado antes da primeira pintura: nada de flash branco no tema escuro.
   A sessão vive em cookie HttpOnly — aqui não há token, só preferência visual. */
const scriptTema = `(function(){try{var k="fluxa:tema";var t=localStorage.getItem(k);var m=window.matchMedia("(prefers-color-scheme: dark)");var aplicar=function(){var escuro=t==="escuro"||((t===null||t==="sistema")&&m.matches);document.documentElement.dataset.tema=escuro?"escuro":"claro";};aplicar();m.addEventListener("change",aplicar);}catch(e){document.documentElement.dataset.tema="claro";}})()`;

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
