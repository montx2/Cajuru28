import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { SCRIPT_TEMA_INICIAL } from "@/lib/preferenciaTema";
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
  themeColor: "#101318",
};

/* Aplicado antes da primeira pintura: nada de flash branco no tema escuro.
   A sessão vive em cookie HttpOnly — aqui não há token, só preferência visual. */


export default function Raiz({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${jetbrainsMono.variable}`} data-tema="escuro" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: SCRIPT_TEMA_INICIAL }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
