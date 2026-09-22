import type { NomeIcone } from "@/components/ui/Icone";
import { ehAdmin, podeOperar } from "./papel";
import { ROTAS_DO_PREFIXO_G } from "./atalhos";

export type GrupoRota = "Visão geral" | "Fiscal" | "Sistema";

export interface RotaApp {
  caminho: string;
  titulo: string;
  grupo: GrupoRota;
  icone: NomeIcone;
  /** Letra do atalho `g + letra`. */
  tecla?: string;
  /** Uma linha do que a tela responde — usada na paleta de comandos. */
  descricao?: string;
  /** Fora do menu, mas com título e trilha (ex.: detalhe da empresa). */
  oculta?: boolean;
  pai?: string;
  visivelPara?: (papel: string) => boolean;
}

/**
 * Registro único de navegação: menu, trilha, título do cabeçalho, paleta de
 * comandos e atalhos `g + letra` leem daqui. Uma rota nova existe num lugar só.
 */
export const ROTAS: RotaApp[] = [
  { caminho: "/dashboard", titulo: "Painel", grupo: "Visão geral", icone: "painel", tecla: "p", descricao: "Está tudo funcionando? Preciso resolver algo?" },
  { caminho: "/dashboard/atencao", titulo: "Precisa da sua atenção", grupo: "Visão geral", icone: "alerta", tecla: "a", descricao: "Decisões pendentes, em ordem de gravidade" },
  { caminho: "/dashboard/execucoes", titulo: "Execuções", grupo: "Visão geral", icone: "execucao", tecla: "x", descricao: "O que a máquina está fazendo agora e o que falhou" },
  { caminho: "/dashboard/documentos", titulo: "Documentos", grupo: "Fiscal", icone: "documento", tecla: "d", descricao: "Acervo: buscar, baixar e conferir XMLs" },
  { caminho: "/dashboard/importacoes", titulo: "Importações", grupo: "Fiscal", icone: "importacao", tecla: "i", descricao: "Disparar captura e acompanhar o sincronismo" },
  { caminho: "/dashboard/empresas", titulo: "Empresas", grupo: "Fiscal", icone: "empresa", tecla: "e", descricao: "Cadastro, certificado e situação por empresa" },
  { caminho: "/dashboard/empresa", titulo: "Empresa", grupo: "Fiscal", icone: "empresa", oculta: true, pai: "/dashboard/empresas" },
  { caminho: "/dashboard/certificados", titulo: "Certificados", grupo: "Fiscal", icone: "certificado", tecla: "c", descricao: "Validade e uso dos certificados A1" },
  { caminho: "/dashboard/relatorios", titulo: "Fechamento", grupo: "Fiscal", icone: "fechamento", tecla: "f", descricao: "Conferência do mês e folha para o dossiê" },
  { caminho: "/dashboard/saude", titulo: "Saúde", grupo: "Sistema", icone: "saude", tecla: "s", descricao: "Componentes, diagnóstico e backup" },
  { caminho: "/dashboard/configuracoes", titulo: "Configurações", grupo: "Sistema", icone: "configuracoes", tecla: "o", descricao: "Ambiente, integrações, alertas e zona de risco" },
  { caminho: "/dashboard/auditoria", titulo: "Auditoria", grupo: "Sistema", icone: "auditoria", tecla: "t", descricao: "Quem fez o quê, e quando", visivelPara: podeOperar },
  { caminho: "/dashboard/usuarios", titulo: "Equipe", grupo: "Sistema", icone: "equipe", tecla: "u", descricao: "Usuários e papéis", visivelPara: ehAdmin },
];

export const GRUPOS: GrupoRota[] = ["Visão geral", "Fiscal", "Sistema"];

export function rotaVisivel(rota: RotaApp, papel: string): boolean {
  return rota.visivelPara ? rota.visivelPara(papel) : true;
}

export function rotasDoMenu(papel: string): RotaApp[] {
  return ROTAS.filter((rota) => !rota.oculta && rotaVisivel(rota, papel));
}

export function rotaDoCaminho(caminho: string): RotaApp | undefined {
  return ROTAS.find((rota) => rota.caminho === caminho);
}

/** Letra → caminho, respeitando o papel (Equipe só existe para admin). */
export function rotaDaTecla(tecla: string, papel: string): string | undefined {
  const caminho = ROTAS_DO_PREFIXO_G[tecla.toLowerCase()];
  if (!caminho) return undefined;
  const rota = rotaDoCaminho(caminho);
  return rota && rotaVisivel(rota, papel) ? caminho : undefined;
}

export interface Migalha {
  rotulo: string;
  href?: string;
}

export function migalhasDoCaminho(caminho: string): Migalha[] {
  const rota = rotaDoCaminho(caminho);
  if (!rota || rota.caminho === "/dashboard") return [];
  const pai = rota.pai ? rotaDoCaminho(rota.pai) : undefined;
  const trilhas: Migalha[] = [{ rotulo: rota.grupo }];
  if (pai) trilhas.push({ rotulo: pai.titulo, href: pai.caminho });
  trilhas.push({ rotulo: rota.titulo });
  return trilhas;
}

export function tituloDoCaminho(caminho: string): string {
  return rotaDoCaminho(caminho)?.titulo ?? "Fluxa";
}
