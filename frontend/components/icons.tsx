"use client";

/**
 * Ícones SVG próprios (sem dependências): traço consistente, `currentColor`.
 * Uso: <Icone nome="dashboard" className="h-5 w-5" />
 */

const CAMINHOS: Record<string, React.ReactNode> = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </>
  ),
  empresa: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="1.5" />
      <path d="M9 21v-4h6v4" />
      <path d="M8 7h2M8 11h2M14 7h2M14 11h2" />
    </>
  ),
  importacao: (
    <>
      <path d="M12 3v12" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 19h16" />
    </>
  ),
  documento: (
    <>
      <path d="M6 2h8l4 4v16H6z" />
      <path d="M14 2v4h4" />
      <path d="M9 12h6M9 16h6" />
    </>
  ),
  grafico: (
    <>
      <path d="M3 21h18" />
      <path d="M7 17v-6M12 17V7M17 17v-9" />
    </>
  ),
  sino: (
    <>
      <path d="M6 9a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6" />
      <path d="M10 20a2 2 0 004 0" />
    </>
  ),
  engrenagem: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12a7 7 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 00-2-1.2L14 2h-4l-.5 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 002 1.2L10 22h4l.5-2.6a7 7 0 002-1.2l2.4 1 2-3.4-2-1.6c.06-.4.1-.8.1-1.2z" />
    </>
  ),
  busca: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </>
  ),
  alerta: (
    <>
      <path d="M12 3L2 20h20z" />
      <path d="M12 9v5" />
      <circle cx="12" cy="17" r="0.5" fill="currentColor" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6" />
      <circle cx="12" cy="7.5" r="0.5" fill="currentColor" />
    </>
  ),
  check: <path d="M4 12.5l5 5L20 6.5" />,
  checkCirculo: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.5 2.5L16 9.5" />
    </>
  ),
  x: <path d="M6 6l12 12M18 6L6 18" />,
  xCirculo: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </>
  ),
  relogio: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  chevronBaixo: <path d="M6 9l6 6 6-6" />,
  chevronDireita: <path d="M9 6l6 6-6 6" />,
  copiar: (
    <>
      <rect x="9" y="9" width="12" height="12" rx="1.5" />
      <path d="M5 15V4a1 1 0 011-1h9" />
    </>
  ),
  baixar: (
    <>
      <path d="M12 3v12" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 21h16" />
    </>
  ),
  imprimir: (
    <>
      <path d="M7 8V3h10v5" />
      <rect x="4" y="8" width="16" height="9" rx="1.5" />
      <rect x="7" y="14" width="10" height="7" />
    </>
  ),
  escudo: (
    <>
      <path d="M12 2l8 3v6c0 5-3.5 9.5-8 11-4.5-1.5-8-6-8-11V5z" />
      <path d="M9 12l2 2 4-4.5" />
    </>
  ),
  raio: <path d="M13 2L4 14h6l-1 8 9-12h-6z" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  sair: (
    <>
      <path d="M14 4H6a1 1 0 00-1 1v14a1 1 0 001 1h8" />
      <path d="M10 12h11M18 8l3 4-3 4" />
    </>
  ),
  calendario: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="1.5" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </>
  ),
  setaDireita: <path d="M4 12h15M14 6l6 6-6 6" />,
  atualizar: (
    <>
      <path d="M20 12a8 8 0 11-2.3-5.6" />
      <path d="M20 3v4h-4" />
    </>
  ),
  chave: (
    <>
      <circle cx="8" cy="14" r="4.5" />
      <path d="M11 11l9-9M17 4l2.5 2.5M14 7l2 2" />
    </>
  ),
  tendencia: (
    <>
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ),
  caixa: (
    <>
      <path d="M3 8l9-5 9 5v8l-9 5-9-5z" />
      <path d="M3 8l9 5 9-5M12 13v8" />
    </>
  ),
  moeda: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9.5c0-1 1.3-1.8 3-1.8s3 .8 3 1.8-1 1.6-3 2-3 1-3 2 1.3 1.8 3 1.8 3-.8 3-1.8" />
      <path d="M12 6.5v11" />
    </>
  ),
  usuarios: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M16 14.2c2.9.3 5.5 2.4 5.5 5.8" />
    </>
  ),
  pasta: (
    <>
      <path d="M3 6a1 1 0 011-1h5l2 2.5h9a1 1 0 011 1V19a1 1 0 01-1 1H4a1 1 0 01-1-1z" />
    </>
  ),
  olho: (
    <>
      <path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  codigo: <path d="M8 6l-5 6 5 6M16 6l5 6-5 6" />,
  estrela: <path d="M12 2l2.9 6.3 6.9.8-5.1 4.7 1.4 6.8-6.1-3.4-6.1 3.4 1.4-6.8L2.2 9.1l6.9-.8z" />,
  filtro: <path d="M3 5h18l-7 8v5l-4 2v-7z" />,
};

export type NomeIcone = keyof typeof CAMINHOS;

export function Icone({
  nome,
  className = "h-5 w-5",
  strokeWidth = 1.8,
}: {
  nome: string;
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {CAMINHOS[nome] ?? CAMINHOS.info}
    </svg>
  );
}

/** Marca do NotasFlow: N estilizado em quadrado com gradiente. */
export function Logomarca({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded-xl bg-gradient-to-br from-accent-bright via-accent to-accent-deep font-serif text-lg font-bold text-white shadow-md ${className}`}
    >
      N
    </span>
  );
}
