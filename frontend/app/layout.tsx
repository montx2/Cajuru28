import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NotasFlow",
  description: "Importação automática de NFS-e, NFe e CT-e",
  // O mesmo ícone do programa: a aba do navegador, o atalho e a bandeja
  // mostram a mesma marca. O arquivo é gerado por `scripts/gerar_icone.py`.
  icons: { icon: "/icone.png", shortcut: "/icone.png", apple: "/icone.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
