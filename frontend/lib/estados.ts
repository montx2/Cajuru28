import type { NomeIcone } from "@/components/ui/Icone";
import { contagemRegressiva, numero, tempoRelativo } from "./format";
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

/** Status livres vindos do Jettax/Morfeu: o texto da API é o rótulo. */
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

export function estadoDoJettaxExecucao(status: string | null | undefined): EstadoVisual {
  return estadoDeIntegracao(status);
}
