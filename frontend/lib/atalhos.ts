export type GrupoAtalho = "Navegação" | "Camadas" | "Tabelas" | "Tela";

export interface Atalho {
  /** Combinação exibida no mapa, já separada por tecla. */
  teclas: string[];
  rotulo: string;
  grupo: GrupoAtalho;
}

/**
 * Registro central: o mapa (`?`), a paleta (⌘K) e o ouvinte global leem daqui.
 * Um atalho que não está nesta lista não existe — é assim que a documentação
 * deixa de mentir.
 */
export const ATALHOS: Atalho[] = [
  { teclas: ["Ctrl", "K"], rotulo: "Abrir a paleta de comandos", grupo: "Camadas" },
  { teclas: ["?"], rotulo: "Ver este mapa de atalhos", grupo: "Camadas" },
  { teclas: ["Esc"], rotulo: "Fechar a camada superior", grupo: "Camadas" },
  { teclas: ["/"], rotulo: "Focar o filtro da tela", grupo: "Tela" },
  { teclas: ["G", "P"], rotulo: "Ir para o Painel", grupo: "Navegação" },
  { teclas: ["G", "A"], rotulo: "Ir para Precisa da sua atenção", grupo: "Navegação" },
  { teclas: ["G", "X"], rotulo: "Ir para Execuções", grupo: "Navegação" },
  { teclas: ["G", "D"], rotulo: "Ir para Documentos", grupo: "Navegação" },
  { teclas: ["G", "I"], rotulo: "Ir para Importações", grupo: "Navegação" },
  { teclas: ["G", "E"], rotulo: "Ir para Empresas", grupo: "Navegação" },
  { teclas: ["G", "C"], rotulo: "Ir para Certificados", grupo: "Navegação" },
  { teclas: ["G", "F"], rotulo: "Ir para Fechamento", grupo: "Navegação" },
  { teclas: ["G", "S"], rotulo: "Ir para Saúde", grupo: "Navegação" },
  { teclas: ["G", "O"], rotulo: "Ir para Configurações", grupo: "Navegação" },
  { teclas: ["G", "T"], rotulo: "Ir para Auditoria", grupo: "Navegação" },
  { teclas: ["G", "U"], rotulo: "Ir para Equipe", grupo: "Navegação" },
  { teclas: ["J"], rotulo: "Selecionar a próxima linha", grupo: "Tabelas" },
  { teclas: ["K"], rotulo: "Selecionar a linha anterior", grupo: "Tabelas" },
  { teclas: ["X"], rotulo: "Marcar ou desmarcar a linha", grupo: "Tabelas" },
  { teclas: ["Enter"], rotulo: "Abrir a linha selecionada", grupo: "Tabelas" },
];

/** Destinos do prefixo `g`. Fora daqui, a tecla não navega. */
export const ROTAS_DO_PREFIXO_G: Record<string, string> = {
  p: "/dashboard",
  a: "/dashboard/atencao",
  x: "/dashboard/execucoes",
  d: "/dashboard/documentos",
  i: "/dashboard/importacoes",
  e: "/dashboard/empresas",
  c: "/dashboard/certificados",
  f: "/dashboard/relatorios",
  s: "/dashboard/saude",
  o: "/dashboard/configuracoes",
  t: "/dashboard/auditoria",
  u: "/dashboard/usuarios",
};

/** Atributo que a tela marca no seu campo de filtro para a tecla `/` encontrá-lo. */
export const ALVO_FILTRO = "data-atalho-filtro";

/** Prefixo único de persistência local (preferências visuais, nunca credencial). */
export const PREFIXO_ARMAZENAMENTO = "notasflow:";
