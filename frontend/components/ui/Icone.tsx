import type { SVGProps } from "react";

/**
 * Ícones do NotasFlow — traço único em grade 24×24, 1,6 px de espessura,
 * `currentColor` sempre. São desenhados aqui (e não importados de um pacote)
 * por três motivos: o peso visual tem que casar com a tipografia de 13 px das
 * tabelas, o conjunto precisa ser fechado (nada de ícone novo por capricho) e o
 * produto não carrega biblioteca para usar 60 glifos.
 *
 * Sem `titulo` o ícone é decorativo (`aria-hidden`): quem dá o nome acessível é
 * o texto ao lado ou o `aria-label` do botão.
 */

const CAMINHOS = {
  painel: (
    <>
      <rect x="3.5" y="3.5" width="7" height="8" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
      <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
      <rect x="3.5" y="14.5" width="7" height="6" rx="1.5" />
    </>
  ),
  alerta: (
    <>
      <path d="M12 4.6 21 19.4H3z" />
      <path d="M12 10.2v4" />
      <path d="M12 17.1h.01" />
    </>
  ),
  execucao: <path d="M3 12.5h3.8l2.4-6.3 3.9 12.1 2.3-5.8H21" />,
  documento: (
    <>
      <path d="M6 3.5h7.2L18.5 9v11.5H6z" />
      <path d="M13 3.5V9h5.5" />
      <path d="M9 13.5h6M9 17h4" />
    </>
  ),
  importacao: (
    <>
      <path d="M12 3.5v10" />
      <path d="M8 10.5l4 4 4-4" />
      <path d="M4.5 17v2.5a1 1 0 001 1h13a1 1 0 001-1V17" />
    </>
  ),
  empresa: (
    <>
      <path d="M4 20.5V5.8a1 1 0 011-1h7.2a1 1 0 011 1v14.7" />
      <path d="M13.2 10.2h5.9a1 1 0 011 1v9.3" />
      <path d="M2.8 20.5h18.4" />
      <path d="M6.8 8.4h3.6M6.8 12h3.6M6.8 15.6h3.6M16 13.6h1.6M16 17h1.6" />
    </>
  ),
  certificado: (
    <>
      <path d="M12 3.2l7.2 2.9v5.6c0 4.3-2.9 7.7-7.2 9.1-4.3-1.4-7.2-4.8-7.2-9.1V6.1z" />
      <path d="M9 12.1l2.2 2.2L15.4 10" />
    </>
  ),
  fechamento: (
    <>
      <path d="M9.2 4.4h5.6v3H9.2z" />
      <path d="M9.2 5.9H6.5a1 1 0 00-1 1v12.6a1 1 0 001 1h11a1 1 0 001-1V6.9a1 1 0 00-1-1h-2.7" />
      <path d="M8.8 14.1l2.1 2.1 4.3-4.3" />
    </>
  ),
  saude: (
    <>
      <path d="M12 20.2s-7.4-4.5-7.4-9.6A4.1 4.1 0 0112 8.2a4.1 4.1 0 017.4 2.4c0 5.1-7.4 9.6-7.4 9.6z" />
      <path d="M6.4 13.4h2.9l1.4-2.4 2 4 1.5-1.6h3" />
    </>
  ),
  configuracoes: (
    <>
      <path d="M3.5 7.5h9M17.5 7.5h3M3.5 12h3M11.5 12h9M3.5 16.5h11M19 16.5h1.5" />
      <circle cx="15" cy="7.5" r="2.3" />
      <circle cx="9" cy="12" r="2.3" />
      <circle cx="16.8" cy="16.5" r="2.3" />
    </>
  ),
  auditoria: (
    <>
      <path d="M8.5 6.5h12M8.5 12h12M8.5 17.5h8" />
      <path d="M4 6.5h.01M4 12h.01M4 17.5h.01" />
    </>
  ),
  equipe: (
    <>
      <circle cx="9.2" cy="8.2" r="3.6" />
      <path d="M2.8 20.2a6.4 6.4 0 0112.8 0" />
      <path d="M16.2 5a3.6 3.6 0 010 6.6" />
      <path d="M17.6 14.4a6.4 6.4 0 013.6 5.8" />
    </>
  ),
  usuario: (
    <>
      <circle cx="12" cy="8.2" r="3.8" />
      <path d="M5 20.2a7 7 0 0114 0" />
    </>
  ),
  busca: (
    <>
      <circle cx="11" cy="11" r="6.8" />
      <path d="M20.2 20.2l-4.4-4.4" />
    </>
  ),
  copiar: (
    <>
      <rect x="8.8" y="8.8" width="11.7" height="11.7" rx="2" />
      <path d="M5.5 15.2H4.8a1 1 0 01-1-1V4.5a1 1 0 011-1h9.7a1 1 0 011 1v.7" />
    </>
  ),
  baixar: (
    <>
      <path d="M12 3.8v10.4" />
      <path d="M7.8 10.6L12 14.8l4.2-4.2" />
      <path d="M4.5 19.5h15" />
    </>
  ),
  enviar: (
    <>
      <path d="M12 20.2V9.8" />
      <path d="M7.8 13.4L12 9.2l4.2 4.2" />
      <path d="M4.5 4.5h15" />
    </>
  ),
  imprimir: (
    <>
      <path d="M7.5 9.5V3.8h9v5.7" />
      <path d="M7.5 15.5h-2a1.7 1.7 0 01-1.7-1.7v-3.1A1.7 1.7 0 015.5 9.5h13a1.7 1.7 0 011.7 1.2v3.1a1.7 1.7 0 01-1.7 1.7h-2" />
      <path d="M7.5 13.5h9v6.7h-9z" />
    </>
  ),
  atualizar: (
    <>
      <path d="M20 12a8 8 0 11-2.6-5.9" />
      <path d="M20.2 4.3v5h-5" />
    </>
  ),
  sincronizar: (
    <>
      <path d="M4.2 10.2A8 8 0 0118 6.4l2 2" />
      <path d="M20 4.2v4.4h-4.4" />
      <path d="M19.8 13.8A8 8 0 016 17.6l-2-2" />
      <path d="M4 19.8v-4.4h4.4" />
    </>
  ),
  adicionar: <path d="M12 5.2v13.6M5.2 12h13.6" />,
  remover: <path d="M5.2 12h13.6" />,
  fechar: <path d="M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8" />,
  editar: (
    <>
      <path d="M4.5 19.5h4L19 9l-4-4-10.5 10.5z" />
      <path d="M14.2 5.8l4 4" />
    </>
  ),
  excluir: (
    <>
      <path d="M4.2 6.8h15.6" />
      <path d="M9.4 6.8V4.9a1 1 0 011-1h3.2a1 1 0 011 1v1.9" />
      <path d="M6.4 6.8l1 13.1a1 1 0 001 .9h7.2a1 1 0 001-.9l1-13.1" />
      <path d="M10.2 10.6v6M13.8 10.6v6" />
    </>
  ),
  sair: (
    <>
      <path d="M14.5 4.2h3.8a1 1 0 011 1v13.6a1 1 0 01-1 1h-3.8" />
      <path d="M10 8.2L6.2 12 10 15.8" />
      <path d="M6.2 12h9" />
    </>
  ),
  menu: <path d="M4 7.2h16M4 12h16M4 16.8h16" />,
  filtrar: <path d="M4 5.5h16l-6.3 7.3v5.9l-3.4 1.8v-7.7z" />,
  colunas: (
    <>
      <rect x="3.2" y="5" width="17.6" height="14" rx="1.8" />
      <path d="M9.2 5v14M15 5v14" />
    </>
  ),
  ordenar: (
    <>
      <path d="M7.5 4.8v14.4M4.6 8.2l2.9-3.4 2.9 3.4" />
      <path d="M16.5 19.2V4.8M13.6 15.8l2.9 3.4 2.9-3.4" />
    </>
  ),
  "chevron-baixo": <path d="M6.4 9.4l5.6 5.6 5.6-5.6" />,
  "chevron-cima": <path d="M6.4 14.6l5.6-5.6 5.6 5.6" />,
  "chevron-esquerda": <path d="M14.6 6.4L9 12l5.6 5.6" />,
  "chevron-direita": <path d="M9.4 6.4L15 12l-5.6 5.6" />,
  "seta-direita": (
    <>
      <path d="M4.2 12h15" />
      <path d="M14 7l5.2 5-5.2 5" />
    </>
  ),
  voltar: (
    <>
      <path d="M19.8 12h-15" />
      <path d="M10 7L4.8 12 10 17" />
    </>
  ),
  externo: (
    <>
      <path d="M14 4.2h5.8V10" />
      <path d="M19.8 4.2L11 13" />
      <path d="M17.5 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7.5a1 1 0 011-1h5" />
    </>
  ),
  ver: (
    <>
      <path d="M2.5 12S6.2 6.2 12 6.2 21.5 12 21.5 12 17.8 17.8 12 17.8 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.9" />
    </>
  ),
  ocultar: (
    <>
      <path d="M4.2 8.1C3 9.4 2.5 12 2.5 12S6.2 17.8 12 17.8c1.6 0 3-.4 4.2-1" />
      <path d="M18.9 15.1c1.4-1.4 2.6-3.1 2.6-3.1S17.8 6.2 12 6.2c-.8 0-1.6.1-2.3.3" />
      <path d="M9.6 9.7a3 3 0 004.2 4.2" />
      <path d="M4.2 4.2l15.6 15.6" />
    </>
  ),
  verificar: <path d="M4.5 12.6l4.9 4.9L19.6 6.8" />,
  "verificar-circulo": (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M8.2 12.3l2.6 2.6 5-5.4" />
    </>
  ),
  negar: (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M12 11.2v5" />
      <path d="M12 8h.01" />
    </>
  ),
  ajuda: (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M9.6 9.6a2.5 2.5 0 114 2.1c-.9.6-1.6 1.1-1.6 2.1" />
      <path d="M12 17h.01" />
    </>
  ),
  relogio: (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M12 7.2V12l3.3 2" />
    </>
  ),
  ampulheta: (
    <>
      <path d="M7 3.5h10M7 20.5h10" />
      <path d="M7.5 3.5v3.2l4.5 4.6 4.5-4.6V3.5" />
      <path d="M7.5 20.5v-3.2l4.5-4.6 4.5 4.6v3.2" />
    </>
  ),
  calendario: (
    <>
      <rect x="3.5" y="5.2" width="17" height="15.3" rx="1.8" />
      <path d="M3.5 10h17" />
      <path d="M8 3.5v3.4M16 3.5v3.4" />
    </>
  ),
  agendador: (
    <>
      <path d="M3.5 10h17V7a1.8 1.8 0 00-1.8-1.8H5.3A1.8 1.8 0 003.5 7z" />
      <path d="M8 3.5v3.4M16 3.5v3.4" />
      <path d="M3.5 10v8.7a1.8 1.8 0 001.8 1.8h5.4" />
      <path d="M20.5 10v3.2" />
      <circle cx="16.6" cy="16.6" r="4" />
      <path d="M16.6 14.8v1.9l1.4.9" />
    </>
  ),
  chave: (
    <>
      <circle cx="8.4" cy="15.6" r="3.9" />
      <path d="M11.2 12.8L20 4" />
      <path d="M16.4 7.6l2.2 2.2M14.2 9.8l2.2 2.2" />
    </>
  ),
  cadeado: (
    <>
      <rect x="4.8" y="10.5" width="14.4" height="9.8" rx="1.8" />
      <path d="M8.2 10.5V7.8a3.8 3.8 0 017.6 0v2.7" />
      <path d="M12 14.4v2.4" />
    </>
  ),
  cofre: (
    <>
      <rect x="3.2" y="4.5" width="17.6" height="15" rx="1.8" />
      <circle cx="10.4" cy="12" r="3.6" />
      <path d="M10.4 8.4v1.2M10.4 14.4v1.2M6.8 12h1.2M12.8 12h1.2M17.6 9v6" />
    </>
  ),
  escudo: <path d="M12 3.2l7.2 2.9v5.6c0 4.3-2.9 7.7-7.2 9.1-4.3-1.4-7.2-4.8-7.2-9.1V6.1z" />,
  raio: <path d="M13.4 3.2L5.6 14h5.3l-1 6.8L18.4 10h-5.4z" />,
  engrenagem: (
    <>
      <circle cx="12" cy="12" r="3.1" />
      <path d="M19.2 12c0-.4 0-.8-.1-1.2l2-1.6-2-3.4-2.4 1a7.2 7.2 0 00-2-1.2L14.2 3H9.8l-.5 2.6c-.7.3-1.4.7-2 1.2l-2.4-1-2 3.4 2 1.6c-.1.4-.1.8-.1 1.2s0 .8.1 1.2l-2 1.6 2 3.4 2.4-1c.6.5 1.3.9 2 1.2l.5 2.6h4.4l.5-2.6c.7-.3 1.4-.7 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z" />
    </>
  ),
  disco: (
    <>
      <rect x="3.2" y="13" width="17.6" height="7.2" rx="1.8" />
      <path d="M5.6 13L8 4.2h8L18.4 13" />
      <path d="M6.8 16.6h.01M10.2 16.6h.01" />
    </>
  ),
  banco: (
    <>
      <ellipse cx="12" cy="6.2" rx="8" ry="2.9" />
      <path d="M4 6.2v11.6c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9V6.2" />
      <path d="M4 12c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9" />
    </>
  ),
  fila: (
    <>
      <path d="M12 3.4l8.8 4.6L12 12.6 3.2 8z" />
      <path d="M3.2 12.6L12 17.2l8.8-4.6" />
      <path d="M3.2 16.8L12 21.4l8.8-4.6" />
    </>
  ),
  trabalhador: (
    <>
      <rect x="6.2" y="6.2" width="11.6" height="11.6" rx="2" />
      <rect x="9.8" y="9.8" width="4.4" height="4.4" rx="1" />
      <path d="M9.4 3.2v3M14.6 3.2v3M9.4 17.8v3M14.6 17.8v3M3.2 9.4h3M3.2 14.6h3M17.8 9.4h3M17.8 14.6h3" />
    </>
  ),
  codigo: (
    <>
      <path d="M8.4 7.8L4 12l4.4 4.2" />
      <path d="M15.6 7.8L20 12l-4.4 4.2" />
      <path d="M13.4 5.2l-2.8 13.6" />
    </>
  ),
  pasta: <path d="M3.5 7.2a1 1 0 011-1h4.3l2 2.2h8.7a1 1 0 011 1v8.9a1 1 0 01-1 1H4.5a1 1 0 01-1-1z" />,
  risco: (
    <>
      <path d="M8.2 3.4h7.6L21 8.6v6.8L15.8 20.6H8.2L3 15.4V8.6z" />
      <path d="M12 8v4.4" />
      <path d="M12 16h.01" />
    </>
  ),
  alvo: (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <circle cx="12" cy="12" r="4.8" />
      <circle cx="12" cy="12" r="1" />
    </>
  ),
  "grafico-barras": (
    <>
      <path d="M3.5 20.2h17" />
      <path d="M7 20.2v-6.4M12 20.2V6.8M17 20.2v-9.4" />
    </>
  ),
  "grafico-pizza": (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M12 3.2V12l7.6 4.4" />
    </>
  ),
  tendencia: (
    <>
      <path d="M3.8 17.2l6-6 3.6 3.6 6.4-7.4" />
      <path d="M19.8 7.4h-4.4M19.8 7.4v4.4" />
    </>
  ),
  moeda: (
    <>
      <rect x="2.8" y="6.2" width="18.4" height="11.6" rx="1.8" />
      <circle cx="12" cy="12" r="2.6" />
      <path d="M6.2 10v4M17.8 10v4" />
    </>
  ),
  somatorio: <path d="M6.4 5.2h11.4l-6.4 6.8 6.4 6.8H6.4" />,
  numero: <path d="M9.4 4.2L7.2 19.8M16.8 4.2l-2.2 15.6M4.4 9.2h15.4M3.8 15h15.4" />,
  play: <path d="M8 5.2l11 6.8-11 6.8z" />,
  pausa: <path d="M9.2 5.2v13.6M14.8 5.2v13.6" />,
  teclado: (
    <>
      <rect x="2.5" y="6.2" width="19" height="11.6" rx="1.8" />
      <path d="M6 9.6h.01M9.4 9.6h.01M12.8 9.6h.01M16.2 9.6h.01M6 12.8h.01M9.4 12.8h.01M12.8 12.8h.01M16.2 12.8h.01M8 15.8h8" />
    </>
  ),
  comando: (
    <>
      <path d="M9.2 9.2h5.6v5.6H9.2z" />
      <path d="M9.2 9.2V6.6A2.6 2.6 0 106.6 9.2zM14.8 9.2V6.6a2.6 2.6 0 112.6 2.6zM14.8 14.8v2.6a2.6 2.6 0 102.6-2.6zM9.2 14.8v2.6a2.6 2.6 0 11-2.6-2.6z" />
    </>
  ),
  sol: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" />
    </>
  ),
  lua: <path d="M20.2 14.6A8.6 8.6 0 019.4 3.8a8.6 8.6 0 1010.8 10.8z" />,
  monitor: (
    <>
      <rect x="3.2" y="4.5" width="17.6" height="12" rx="1.8" />
      <path d="M8.4 20.2h7.2M12 16.5v3.7" />
    </>
  ),
  sino: (
    <>
      <path d="M6.2 9.6a5.8 5.8 0 0111.6 0c0 4.2 1.6 5.6 2 6.2H4.2c.4-.6 2-2 2-6.2z" />
      <path d="M10 19.2a2.1 2.1 0 004 0" />
    </>
  ),
  "lista-verificacao": (
    <>
      <path d="M3.6 6.4l1.6 1.6 3-3.2M3.6 12l1.6 1.6 3-3.2M3.6 17.6l1.6 1.6 3-3.2" />
      <path d="M11.4 6.8h9M11.4 12.4h9M11.4 18h6" />
    </>
  ),
  historico: (
    <>
      <path d="M3.8 12a8.2 8.2 0 108.2-8.2A8.1 8.1 0 006 6.4" />
      <path d="M3.6 3.8v3.4h3.4" />
      <path d="M12 8v4.3l2.9 1.7" />
    </>
  ),
  arrastar: <path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" />,
  caixa: (
    <>
      <path d="M3.6 8.2 12 4l8.4 4.2v7.6L12 20l-8.4-4.2z" />
      <path d="M3.6 8.2 12 12.4l8.4-4.2M12 12.4V20" />
    </>
  ),
  webhook: (
    <>
      <circle cx="7" cy="17" r="2.6" />
      <circle cx="17" cy="17" r="2.6" />
      <circle cx="12" cy="7" r="2.6" />
      <path d="M9.2 8.4 7.4 14.4M14.8 8.4l1.8 6M9.6 17h4.8" />
    </>
  ),
} as const;

export type NomeIcone = keyof typeof CAMINHOS;

export const NOMES_ICONE = Object.keys(CAMINHOS) as NomeIcone[];

export interface IconeProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  nome: NomeIcone;
  /** Classe de tamanho — o padrão casa com o corpo de 14 px. */
  className?: string;
  espessura?: number;
  /** Presente = o ícone é informativo e precisa de nome acessível. */
  titulo?: string;
}

export function Icone({ nome, className = "h-4 w-4", espessura = 1.6, titulo, ...props }: IconeProps) {
  const informativo = Boolean(titulo);
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={espessura}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={informativo ? "img" : undefined}
      aria-hidden={informativo ? undefined : true}
      focusable="false"
      {...props}
    >
      {titulo ? <title>{titulo}</title> : null}
      {CAMINHOS[nome]}
    </svg>
  );
}
