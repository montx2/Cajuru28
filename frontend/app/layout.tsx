import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NotasFlow",
  description: "Importação automática de NFS-e, NFe e CT-e",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
