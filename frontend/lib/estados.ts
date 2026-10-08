import type { NomeIcone } from "@/components/ui/Icone";
import { contagem, contagemRegressiva, numero, tempoDecorrido, tempoRelativo } from "./format";
import type {
  DocumentoFiscal,
  EstadoSincronizacao,
  NivelAlerta,
  ResumoCertificado,
  StatusExecucao,
  StatusGeral,
} from "./types";
import { ROTULO_STATUS_LOTE, ROTULO_STATUS_SELECAO } from "./types";

/**
 * Estado → aparência. Este arquivo é a única tradução entre o vocabulário da
 * API e o vocabulário visual do produto; nenhuma tela escolhe cor por conta.
 *
 * A regra que não pode ser quebrada: **esperar não é falhar**. Janela oficial
 * da SEFAZ, cStat 656 e cota esgotada são `espera` (âmbar) — vermelho aqui
 * faz o operador clicar em "tentar de novo" antes da hora, e clicar antes da
 * hora zera o cronômetro.
 */

export type Tom = "ok" | "espera" | "erro" | "info" | "neutro" | "acento";

export interface EstadoVisual {
  tom: Tom;
  rotulo: string;
  icone: NomeIcone;
  /** Só para trabalho em curso — é o único movimento contínuo do produto. */
  pulsa?: boolean;
  /** Camada absoluta para `title`: o relativo mora no rótulo. */
  absoluto?: string;
}

/* ── Execuções ───────────────────────────────────────────────────────────── */

/**
 * Execução que ainda pode terminar. `finalizado_em` é a fonte principal, mas
 * NÃO é a única: o estado final (falhou/concluída) manda mais que o campo.
 * Uma falha de enfileiramento antiga pode não ter o fim gravado — e desenhar
 * isso como "em curso" faz uma captura que morreu parecer trabalho rodando.
 */
export function execucaoEmAberto(execucao: {
  status: StatusExecucao | string;
  finalizado_em: string | null;
}): boolean {
  if (execucao.finalizado_em) return false;
  return execucao.status === "em_andamento" || execucao.status === "aguardando";
}

/** O que a central de Execuções escreve quando o fim não foi gravado. */
export const SEM_FIM_REGISTRADO = "sem fim registrado";

/**
 * Duração para exibir. Só uma execução aberta pode dizer "em curso"; encerrada
 * sem horário de fim é dívida de dado, e a tela admite isso em vez de inventar
 * um número que cresce sozinho a cada segundo.
 */
export function duracaoDaExecucao(
  execucao: { status: StatusExecucao | string; iniciado_em: string; finalizado_em: string | null },
  agora = Date.now(),
): string {
  if (execucao.finalizado_em) {
    return tempoDecorrido(execucao.iniciado_em, execucao.finalizado_em, agora);
  }
  return execucaoEmAberto(execucao) ? "em curso" : SEM_FIM_REGISTRADO;
}

/**
 * "Próximo passo" de uma execução que falhou, por natureza da falha.
 *
 * Um conselho só servia para todo erro: "confira o certificado A1 e a janela da
 * SEFAZ". Quando a fila do próprio Fluxa está fora do ar, isso manda o contador
 * mexer no lugar errado — e o certificado dele está bom.
 */
const ORIENTACAO_POR_FALHA: Record<string, string> = {
  fila_indisponivel:
    "Nada foi consultado na SEFAZ e a cota do dia segue inteira. Confira se os serviços de fila e worker estão no ar e dispare de novo.",
  cadastro:
    "É cadastro, não SEFAZ: resolva o cadastro desta empresa (certificado A1, UF ou situação da empresa) e reprocesse o período.",
  ambiente_fiscal:
    "O ambiente fiscal não respondeu dentro das tentativas — nada foi perdido. O agendador volta sozinho na próxima varredura; se persistir, veja a tela Saúde.",
  importacao_parcial:
    "As notas que chegaram foram gravadas e os lotes com problema ficaram preservados. Reprocesse para ler os lotes de novo, sem repetir a consulta fiscal.",
  sistema:
    "Falha interna do Fluxa, não da SEFAZ: nada foi consultado. Veja a tela Saúde e reprocesse depois.",
  captura:
    "Confira se o certificado A1 da empresa está válido e se a SEFAZ não está em janela de espera. Depois, reprocesse o período.",
};

export function orientacaoDaExecucao(falha: string | null | undefined): string {
  return ORIENTACAO_POR_FALHA[falha ?? ""] ?? ORIENTACAO_POR_FALHA.captura;
}

export function estadoDaExecucao(status: StatusExecucao | string): EstadoVisual {
  switch (status) {
    case "em_andamento":
      return { tom: "info", rotulo: "Em andamento", icone: "execucao", pulsa: true };
    case "aguardando":
      // cStat 656 / "nenhum documento novo": a SEFAZ pediu a janela de 1 hora.
      return { tom: "espera", rotulo: "Aguardando janela", icone: "ampulheta" };
    case "concluida":
      return { tom: "ok", rotulo: "Concluída", icone: "verificar-circulo" };
    case "erro":
      return { tom: "erro", rotulo: "Falhou", icone: "negar" };
    default:
      return { tom: "neutro", rotulo: String(status || "Desconhecido"), icone: "info" };
  }
}

/* ── Situação geral do sistema ───────────────────────────────────────────── */

export interface EstadoGeralVisual extends EstadoVisual {
  /** Frase curta que encabeça o Painel. */
  titulo: string;
  /** O que o operador deve entender sem ler detalhe nenhum. */
  resumo: string;
}

export function estadoGeral(status: StatusGeral | string): EstadoGeralVisual {
  switch (status) {
    case "operando":
      return {
        tom: "ok",
        rotulo: "Operando",
        titulo: "Operação estável",
        resumo: "A captura automática está em dia. Nada exige decisão agora.",
        icone: "verificar-circulo",
      };
    case "atencao":
      return {
        tom: "espera",
        rotulo: "Com pendências",
        titulo: "Operando com pendências",
        resumo: "A automação segue rodando, mas há itens esperando uma decisão sua.",
        icone: "alerta",
      };
    case "critico":
      return {
        tom: "erro",
        rotulo: "Crítico",
        titulo: "Uma ação precisa de você",
        resumo: "Existe item crítico na fila de atenção. Sem ação, documentos podem faltar no fechamento.",
        icone: "risco",
      };
    default:
      return {
        tom: "neutro",
        rotulo: "Sem leitura",
        titulo: "Estado ainda não lido",
        resumo: "O painel ainda não conseguiu ler o estado da operação.",
        icone: "info",
      };
  }
}

/* ── Alertas ─────────────────────────────────────────────────────────────── */

export function estadoDoNivel(nivel: NivelAlerta | string): EstadoVisual {
  switch (nivel) {
    case "critico":
      return { tom: "erro", rotulo: "Crítico", icone: "risco" };
    case "atencao":
      return { tom: "espera", rotulo: "Importante", icone: "alerta" };
    case "info":
      return { tom: "info", rotulo: "Informativo", icone: "info" };
    default:
      return { tom: "neutro", rotulo: String(nivel || "—"), icone: "info" };
  }
}

/** Ordem de gravidade usada para listar "de cima para baixo". */
export const PESO_NIVEL: Record<string, number> = { critico: 0, atencao: 1, info: 2 };

export function compararPorGravidade(a: { nivel: string }, b: { nivel: string }): number {
  return (PESO_NIVEL[a.nivel] ?? 9) - (PESO_NIVEL[b.nivel] ?? 9);
}

/* ── Componentes de infraestrutura ───────────────────────────────────────── */

export function estadoDoComponente(status: string): EstadoVisual {
  switch (status) {
    case "ok":
      return { tom: "ok", rotulo: "Operacional", icone: "verificar-circulo" };
    case "atencao":
      return { tom: "espera", rotulo: "Degradado", icone: "alerta" };
    case "erro":
      return { tom: "erro", rotulo: "Fora do ar", icone: "negar" };
    case "desligado":
      return { tom: "neutro", rotulo: "Desligado", icone: "pausa" };
    default:
      return { tom: "neutro", rotulo: "Desconhecido", icone: "ajuda" };
  }
}

/* ── Prévia e lote de importação ─────────────────────────────────────────── */

const TOM_STATUS_SELECAO: Record<string, Tom> = {
  ok: "ok",
  enfileirada: "info",
  em_cooldown: "espera",
  ja_em_andamento: "info",
  em_andamento: "info",
  sem_certificado: "erro",
  sem_uf: "erro",
  fila_indisponivel: "erro",
  erro: "erro",
};

const ICONE_STATUS_SELECAO: Record<string, NomeIcone> = {
  ok: "verificar-circulo",
  enfileirada: "fila",
  em_cooldown: "ampulheta",
  ja_em_andamento: "execucao",
  em_andamento: "execucao",
  sem_certificado: "certificado",
  sem_uf: "alerta",
  fila_indisponivel: "banco",
  erro: "negar",
};

export function estadoDaSelecao(status: string): EstadoVisual {
  return {
    tom: TOM_STATUS_SELECAO[status] ?? "neutro",
    rotulo: ROTULO_STATUS_SELECAO[status] ?? ROTULO_STATUS_LOTE[status] ?? status,
    icone: ICONE_STATUS_SELECAO[status] ?? "info",
  };
}

export function estadoDoLote(status: string): EstadoVisual {
  return {
    tom: TOM_STATUS_SELECAO[status] ?? "neutro",
    rotulo: ROTULO_STATUS_LOTE[status] ?? status,
    icone: ICONE_STATUS_SELECAO[status] ?? "info",
  };
}

/* ── Certificados ────────────────────────────────────────────────────────── */

export function estadoDoCertificado(
  certificado: Pick<ResumoCertificado, "tem_certificado" | "validade" | "dias_para_vencer" | "vencido" | "vence_em_breve">
): EstadoVisual {
  if (!certificado.tem_certificado) {
    return { tom: "erro", rotulo: "Sem certificado A1", icone: "certificado" };
  }
  if (certificado.vencido) {
    const dias = Math.abs(certificado.dias_para_vencer ?? 0);
    return {
      tom: "erro",
      rotulo: dias > 0 ? `Vencido há ${numero(dias)} ${dias === 1 ? "dia" : "dias"}` : "Vencido",
      icone: "negar",
    };
  }
  if (certificado.vence_em_breve) {
    return {
      tom: "espera",
      rotulo: `Vence em ${numero(certificado.dias_para_vencer ?? 0)} dias`,
      icone: "relogio",
    };
  }
  return {
    tom: "ok",
    rotulo:
      certificado.dias_para_vencer !== null && certificado.dias_para_vencer !== undefined
        ? `Válido · ${numero(certificado.dias_para_vencer)} dias`
        : "Válido",
    icone: "verificar-circulo",
  };
}

/* ── Sincronismo por empresa + tipo ──────────────────────────────────────── */

/**
 * A situação que responde "esta combinação precisa de mim?".
 * A ordem dos testes é a ordem de gravidade: nada adianta dizer "em dia" para
 * uma empresa cujo documento já saiu da janela de distribuição da SEFAZ.
 */
export function estadoDaSincronizacao(estado: EstadoSincronizacao, agora = Date.now()): EstadoVisual {
  if (estado.em_andamento) {
    return {
      tom: "info",
      rotulo: "Varrendo agora",
      icone: "execucao",
      pulsa: true,
      absoluto: estado.ultima_consulta_em ? tempoRelativo(estado.ultima_consulta_em, agora) : undefined,
    };
  }
  if ((estado.lotes_pendentes ?? 0) > 0) {
    return {
      tom: "erro", rotulo: "Importação parcial", icone: "alerta",
      absoluto: `${contagem(estado.lotes_pendentes!, "lote recebido precisa", "lotes recebidos precisam")} de reprocessamento local. As respostas foram preservadas.`,
    };
  }
  if (estado.risco_documento_fora_da_distribuicao) {
    return {
      tom: "erro",
      rotulo: "Risco de perda",
      icone: "risco",
      absoluto:
        estado.dias_sem_varrer !== null
          ? `${numero(estado.dias_sem_varrer)} dias sem varrer · a SEFAZ guarda cerca de 3 meses`
          : "A SEFAZ guarda cerca de 3 meses",
    };
  }
  if (estado.travado) {
    return {
      tom: "erro",
      rotulo: "Travado",
      icone: "negar",
      absoluto: estado.motivo_bloqueio ?? undefined,
    };
  }
  const liberacao = contagemRegressiva(estado.liberacao_em, agora);
  if (estado.bloqueado_ate || liberacao) {
    return {
      tom: "espera",
      rotulo: liberacao ? `Na janela · libera ${liberacao}` : estado.liberacao_rotulo || "Na janela da SEFAZ",
      icone: "ampulheta",
      absoluto: estado.liberacao_em ?? estado.bloqueado_ate ?? undefined,
    };
  }
  if (!estado.sincronizar_automaticamente) {
    return { tom: "neutro", rotulo: "Automático desligado", icone: "pausa" };
  }
  if (estado.pendencia > 0) {
    return {
      tom: "espera",
      rotulo: `${numero(estado.pendencia)} ${estado.pendencia === 1 ? "pendente" : "pendentes"}`,
      icone: "fila",
    };
  }
  if (!estado.ultima_consulta_em) {
    return { tom: "neutro", rotulo: "Nunca consultada", icone: "ajuda" };
  }
  if (estado.nunca_consultado) {
    return { tom: "neutro", rotulo: "Cursor não confirmado", icone: "ajuda", absoluto: "O ambiente ainda não informou o NSU máximo; não é confirmação de acervo completo." };
  }
  if (estado.em_dia) {
    return { tom: "ok", rotulo: "Em dia", icone: "verificar-circulo" };
  }
  if (estado.dias_sem_varrer !== null && estado.dias_sem_varrer > 7) {
    return {
      tom: "espera",
      rotulo: `${numero(estado.dias_sem_varrer)} dias sem varrer`,
      icone: "relogio",
    };
  }
  return { tom: "ok", rotulo: "Em dia", icone: "verificar-circulo" };
}

/* ── Documentos ──────────────────────────────────────────────────────────── */

export function estadoDoDocumento(documento: Pick<DocumentoFiscal, "status" | "leiaute">): EstadoVisual {
  if (documento.status === "cancelada") {
    return { tom: "erro", rotulo: "Cancelada", icone: "negar" };
  }
  if (documento.leiaute === "resumo") {
    // A SEFAZ entregou o resumo (resNFe); o XML completo vem pela chave.
    return { tom: "espera", rotulo: "Só resumo", icone: "documento" };
  }
  if (documento.leiaute === "metadados") {
    return { tom: "espera", rotulo: "Sem XML da fonte", icone: "documento" };
  }
  return { tom: "neutro", rotulo: "Normal", icone: "verificar" };
}

/* ── Fechamento, backup e integrações ────────────────────────────────────── */

export function estadoDaConferencia(status: string): EstadoVisual {
  switch (status) {
    case "completa":
      return { tom: "ok", rotulo: "Pronta para fechar", icone: "verificar-circulo" };
    case "parcial":
      return { tom: "espera", rotulo: "Parcial", icone: "alerta" };
    case "pendente":
      return { tom: "espera", rotulo: "Pendente", icone: "ampulheta" };
    case "critico":
      return { tom: "erro", rotulo: "Crítica", icone: "risco" };
    default:
      return { tom: "neutro", rotulo: status || "—", icone: "info" };
  }
}

export function estadoDoBackup(status: string): EstadoVisual {
  switch (status) {
    case "ok":
      return { tom: "ok", rotulo: "Concluído", icone: "verificar-circulo" };
    case "em_andamento":
      return { tom: "info", rotulo: "Gerando pacote", icone: "execucao", pulsa: true };
    case "erro":
      return { tom: "erro", rotulo: "Falhou", icone: "negar" };
    default:
      return { tom: "neutro", rotulo: status || "—", icone: "info" };
  }
}

/** Status livres vindos de integrações externas: o texto da API é o rótulo. */
export function estadoDeIntegracao(status: string | null | undefined): EstadoVisual {
  const bruto = (status ?? "").trim().toLowerCase();
  if (!bruto) return { tom: "neutro", rotulo: "Não registrada", icone: "ajuda" };
  if (["ok", "ativa", "ativo", "registrada", "registrado", "sucesso", "concluida", "concluída"].includes(bruto)) {
    return { tom: "ok", rotulo: status as string, icone: "verificar-circulo" };
  }
  if (["erro", "falha", "failed", "error"].some((termo) => bruto.includes(termo))) {
    return { tom: "erro", rotulo: status as string, icone: "negar" };
  }
  if (["pendente", "andamento", "aguardando", "fila"].some((termo) => bruto.includes(termo))) {
    return { tom: "espera", rotulo: status as string, icone: "ampulheta" };
  }
  return { tom: "neutro", rotulo: status as string, icone: "info" };
}
