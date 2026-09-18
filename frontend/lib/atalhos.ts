export type Atalho = { teclas: string[]; rotulo: string; grupo: "Navegação" | "Ações" | "Tabelas" };

export const ATALHOS: Atalho[] = [
  { teclas: ["Ctrl/⌘", "K"], rotulo: "Abrir paleta de comandos", grupo: "Ações" },
  { teclas: ["?"], rotulo: "Ver atalhos", grupo: "Ações" },
  { teclas: ["/"], rotulo: "Focar filtro da tela", grupo: "Ações" },
  { teclas: ["G", "D"], rotulo: "Ir para documentos", grupo: "Navegação" },
  { teclas: ["G", "E"], rotulo: "Ir para empresas", grupo: "Navegação" },
  { teclas: ["G", "I"], rotulo: "Ir para importações", grupo: "Navegação" },
  { teclas: ["G", "P"], rotulo: "Ir para o painel", grupo: "Navegação" },
  { teclas: ["J"], rotulo: "Próxima linha", grupo: "Tabelas" },
  { teclas: ["K"], rotulo: "Linha anterior", grupo: "Tabelas" },
  { teclas: ["Esc"], rotulo: "Fechar a camada superior", grupo: "Ações" },
];
