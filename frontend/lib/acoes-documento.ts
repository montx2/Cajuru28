import type { NomeIcone } from "@/components/ui/Icone";
import { dataHora, numero } from "./format";
import type { DocumentoFiscal } from "./types";
import type { Tom } from "./estados";

/**
 * Hierarquia de ação de um documento fiscal — **uma** regra para todas as telas.
 *
 * ## Por que este arquivo existe
 *
 * A ficha lateral chegou a empilhar três cartões de aviso e seis botões na
 * mesma coluna, com a MESMA ação escrita de dois jeitos ("Tentar buscar XML
 * completo na SEFAZ" num cartão, "Buscar XML completo na SEFAZ agora" no outro)
 * e aparecendo duas vezes na tela de uma nota com erro e mais de 12 dias. O
 * operador não conseguia dizer qual botão resolvia o problema dele.
 *
 * Este módulo é a tradução única de `estado do documento` → `o que dá para
 * fazer`. Nenhuma tela decide isso por conta. As regras:
 *
 * 1. **uma ação primária por documento**, decidida pelo estado dele;
 * 2. **no máximo duas secundárias** ao lado; o resto vai para o menu "⋯";
 * 3. **excluir nunca fica ao lado do botão principal** (é destrutiva e rara);
 * 4. **um rótulo só por ação** — `ROTULO_ACAO` é a forma definitiva, usada na
 *    ficha, na lista, nos alertas e nos diálogos;
 * 5. **nada é desabilitado em silêncio**: `motivo` explica sempre.
 */

export type IdAcaoDocumento =
  | "buscar-xml-completo"
  | "manifestar-operacao"
  | "baixar-xml"
  | "ver-empresa"
  | "excluir-documento";

/**
 * A forma definitiva de cada rótulo. Trocar aqui troca no produto inteiro —
 * é o ponto único que impede o mesmo botão de voltar a ter dois nomes.
 */
export const ROTULO_ACAO: Record<IdAcaoDocumento, string> = {
  "buscar-xml-completo": "Buscar XML completo",
  "manifestar-operacao": "Manifestar operação",
  "baixar-xml": "Baixar XML",
  "ver-empresa": "Ver empresa",
  "excluir-documento": "Excluir documento",
};

/** Rótulos das ações em lote — mesma ação, escopo maior, contagem no nome. */
export const ROTULO_ACAO_LOTE = {
  /** Muitos documentos de uma vez (`completar-xmls`). */
  buscarXml: "Buscar todos os XMLs",
  /** Uma manifestação para N notas, com a lista antes do envio. */
  manifestar: (quantidade: number) => `Manifestar as ${numero(quantidade)} notas`,
} as const;

/** A Ciência da Operação (210210) só é aceita até 10 dias da autorização. */
const DIAS_CIENCIA = 10;
/**
 * Folga: a data de emissão é um **piso** (a autorização nunca vem antes dela),
 * então só oferecemos a conclusiva com margem — propor um evento que a SEFAZ
 * recusaria por 596 é pior do que esperar dois dias.
 */
const FOLGA_DIAS = 2;

export interface AcaoDocumento {
  id: IdAcaoDocumento;
  rotulo: string;
  icone: NomeIcone;
  desabilitado: boolean;
  /** Por que está indisponível — desabilitado sem explicação parece defeito. */
  motivo?: string;
}

export interface HierarquiaAcoesDocumento {
  /** No máximo uma, e sempre a que resolve o estado atual do documento. */
  primaria: AcaoDocumento | null;
  /** No máximo duas ao lado da primária. */
  secundarias: AcaoDocumento[];
  /** O que sobrou, dentro do menu "⋯". */
  menu: AcaoDocumento[];
}

export type DocumentoParaAcoes = Pick<
  DocumentoFiscal,
  | "status"
  | "leiaute"
  | "data_emissao"
  | "motivo_cancelamento"
  | "cancelado_em"
  | "manifestado_em"
  | "manifestacao_erro"
  | "manifestacao_cstat"
> & {
  /** Só o detalhe sabe se o arquivo ainda está no disco. */
  xml_disponivel?: boolean;
};

const ICONE_ACAO: Record<IdAcaoDocumento, NomeIcone> = {
  "buscar-xml-completo": "sincronizar",
  "manifestar-operacao": "documento",
  "baixar-xml": "baixar",
  "ver-empresa": "empresa",
  "excluir-documento": "excluir",
};

function acao(
  id: IdAcaoDocumento,
  desabilitado = false,
  motivo?: string
): AcaoDocumento {
  return { id, rotulo: ROTULO_ACAO[id], icone: ICONE_ACAO[id], desabilitado, motivo };
}

/**
 * A nota passou do prazo da Ciência da Operação?
 *
 * Exportada porque a lista e os alertas usam a mesma conta: quando ela vale,
 * "Buscar XML completo" não resolve e a única saída é a manifestação conclusiva.
 */
export function cienciaProvavelmenteVencida(documento: DocumentoParaAcoes): boolean {
  if (documento.leiaute !== "resumo" || documento.manifestado_em) return false;
  if (!documento.data_emissao) return false;
  const emissao = new Date(documento.data_emissao).getTime();
  if (Number.isNaN(emissao)) return false;
  const limite = (DIAS_CIENCIA + FOLGA_DIAS) * 24 * 60 * 60 * 1000;
  return Date.now() - emissao > limite;
}

/** Qual ação resolve o estado atual deste documento — a primária. */
export function idDaAcaoPrimaria(documento: DocumentoParaAcoes): IdAcaoDocumento {
  // 596 = a Ciência chegou tarde. Repetir a busca nunca vai funcionar: só um
  // evento conclusivo libera o XML, e quem escolhe qual é o operador.
  if (documento.manifestacao_cstat === "596") return "manifestar-operacao";
  if (documento.leiaute === "resumo") {
    return cienciaProvavelmenteVencida(documento)
      ? "manifestar-operacao"
      : "buscar-xml-completo";
  }
  // Completo, metadados ou cancelada: o que resta é levar o arquivo.
  return "baixar-xml";
}

export interface OpcoesAcoes {
  /** Painel aberto só para leitura (ex.: vindo de um relatório). */
  somenteLeitura?: boolean;
  /** A tela dona da lista é quem confirma a exclusão. */
  podeExcluir?: boolean;
}

/**
 * Monta a hierarquia: 1 primária + até 2 secundárias + o menu "⋯".
 *
 * A ordem das secundárias é fixa de propósito: a posição de um botão é memória
 * muscular, e ela não pode mudar conforme o estado do documento.
 */
export function acoesDoDocumento(
  documento: DocumentoParaAcoes,
  opcoes: OpcoesAcoes = {}
): HierarquiaAcoesDocumento {
  const { somenteLeitura = false, podeExcluir = false } = opcoes;
  const motivoLeitura = somenteLeitura
    ? "Este documento está aberto em modo somente leitura."
    : undefined;

  const idPrimaria = idDaAcaoPrimaria(documento);
  let motivoPrimaria = motivoLeitura;

  if (!somenteLeitura) {
    if (idPrimaria === "baixar-xml" && documento.leiaute === "metadados") {
      motivoPrimaria =
        "A fonte de origem não disponibilizou XML para este documento. Exporte o período para obter o JSON normalizado.";
    } else if (idPrimaria === "baixar-xml" && documento.xml_disponivel === false) {
      motivoPrimaria =
        "O arquivo não está no disco do servidor. Capture novamente pela SEFAZ antes de baixar.";
    } else if (
      (idPrimaria === "buscar-xml-completo" || idPrimaria === "manifestar-operacao") &&
      documento.status === "cancelada"
    ) {
      motivoPrimaria =
        "Nota cancelada: não há operação a manifestar nem XML a buscar. O XML que existe pode ser baixado pelo menu ⋯.";
    }
  }

  const primaria = acao(idPrimaria, motivoPrimaria !== undefined, motivoPrimaria);

  const verEmpresa = acao("ver-empresa", false);
  const secundarias = [verEmpresa];

  const menu: AcaoDocumento[] = [];
  // Quando a primária está bloqueada por cancelamento, o download continua
  // fazendo sentido (a nota cancelada também se arquiva): entra no menu.
  if (primaria.desabilitado && primaria.id !== "baixar-xml" && documento.leiaute !== "metadados") {
    menu.push(acao("baixar-xml", somenteLeitura, motivoLeitura));
  }
  if (podeExcluir) {
    menu.push(
      acao(
        "excluir-documento",
        somenteLeitura,
        motivoLeitura ?? "Remove o registro e o XML do disco. Não tem volta."
      )
    );
  }

  return { primaria, secundarias: secundarias.slice(0, 2), menu };
}

/* ── Situação: um bloco, não três ─────────────────────────────────────────── */

export interface SituacaoDocumento {
  tom: Tom;
  titulo: string;
  /**
   * Um parágrafo por **fato**. 596 + resumo são dois fatos de UM problema —
   * por isso dois parágrafos no mesmo bloco, nunca dois cartões empilhados.
   */
  paragrafos: string[];
  /** Rótulo da ação que resolve — sempre igual ao botão primário. */
  acao?: string;
}

interface Fato {
  tom: Tom;
  titulo: string;
  paragrafos: string[];
  acao?: string;
}

/**
 * Os fatos que explicam por que este documento não está pronto.
 *
 * Cada fato tem seu título e sua causa; `situacaoDoDocumento` junta todos num
 * bloco só. Antes eram três `div` irmãos, cada um com o próprio botão, e o
 * operador lia a mesma instrução duas vezes com palavras diferentes.
 */
export function fatosDoDocumento(documento: DocumentoParaAcoes): Fato[] {
  const fatos: Fato[] = [];

  if (documento.status === "cancelada") {
    fatos.push({
      tom: "erro",
      titulo: "Nota cancelada",
      paragrafos: [
        documento.motivo_cancelamento
          ? `Motivo do cancelamento: ${documento.motivo_cancelamento}${
              documento.cancelado_em ? ` · ${dataHora(documento.cancelado_em)}` : ""
            }`
          : "O evento de cancelamento chegou da SEFAZ sem motivo informado.",
      ],
    });
  }

  if (documento.xml_disponivel === false && documento.leiaute === "completo") {
    fatos.push({
      tom: "erro",
      titulo: "O XML não está no disco do servidor",
      paragrafos: [
        "O cadastro diz que o XML completo foi capturado, mas o arquivo não foi encontrado. Sem recapturar pela SEFAZ (dentro do horizonte de distribuição) não há como recuperá-lo.",
      ],
    });
  }

  if (documento.manifestacao_cstat === "596") {
    fatos.push({
      tom: "erro",
      titulo: "A Ciência da Operação não é mais aceita para esta nota",
      paragrafos: [
        `Ela passou dos ${DIAS_CIENCIA} dias contados da autorização e a SEFAZ recusou o evento (cStat 596). Repetir a busca não resolve.`,
        "O XML completo só é liberado por uma manifestação conclusiva — Confirmação da Operação, se a mercadoria foi recebida.",
      ],
      acao: ROTULO_ACAO["manifestar-operacao"],
    });
  } else if (documento.manifestacao_erro) {
    fatos.push({
      tom: "erro",
      titulo: "Ciência da Operação recusada",
      paragrafos: [documento.manifestacao_erro],
      acao: ROTULO_ACAO["buscar-xml-completo"],
    });
  }

  if (documento.leiaute === "resumo") {
    const vencida = cienciaProvavelmenteVencida(documento);
    fatos.push({
      tom: "espera",
      titulo: "Falta o XML completo desta nota",
      paragrafos: [
        documento.manifestado_em
          ? `Ciência da Operação registrada em ${dataHora(documento.manifestado_em)}. A SEFAZ está liberando o XML completo (procNFe).`
          : "A nota chegou em resumo (resNFe): o sistema registra a Ciência da Operação e busca o XML completo pela chave, com o certificado A1 da empresa.",
        ...(vencida
          ? [
              `A nota tem mais de ${DIAS_CIENCIA} dias da emissão: se a Ciência for recusada com 596, o XML só sai com uma manifestação conclusiva.`,
            ]
          : []),
      ],
      // Quando a Ciência já venceu, a busca não resolve — a saída é manifestar.
      acao: vencida
        ? ROTULO_ACAO["manifestar-operacao"]
        : documento.manifestacao_cstat === "596"
          ? undefined
          : ROTULO_ACAO["buscar-xml-completo"],
    });
  }

  if (documento.leiaute === "metadados") {
    fatos.push({
      tom: "espera",
      titulo: "A fonte não entregou XML para este documento",
      paragrafos: [
        "A NFS-e chegou por metadados. Exporte o período para obter o JSON normalizado — o sistema não inventa um XML fiscal inexistente.",
      ],
    });
  }

  if (
    fatos.length === 0 &&
    documento.manifestado_em &&
    documento.leiaute === "completo"
  ) {
    fatos.push({
      tom: "neutro",
      titulo: `Ciência da Operação registrada em ${dataHora(documento.manifestado_em)}.`,
      paragrafos: [],
    });
  }

  return fatos;
}

const ORDEM_TOM: Tom[] = ["erro", "espera", "info", "neutro"];

/**
 * O bloco único de situação — `null` quando não há nada a dizer.
 *
 * O tom é o do fato mais grave: um bloco com 596 (erro) e resumo (espera) é
 * lido como erro, porque é isso que o operador precisa sentir.
 */
export function situacaoDoDocumento(documento: DocumentoParaAcoes): SituacaoDocumento | null {
  const fatos = fatosDoDocumento(documento);
  if (fatos.length === 0) return null;
  const tom =
    ORDEM_TOM.find((candidato) => fatos.some((fato) => fato.tom === candidato)) ?? "neutro";
  // O primeiro fato dá o título; os demais entram como parágrafos do mesmo
  // bloco, cada um com a própria causa.
  const [primeiro, ...resto] = fatos;
  const paragrafos = [
    ...primeiro.paragrafos,
    ...resto.flatMap((fato) => [fato.titulo, ...fato.paragrafos]),
  ];
  // A ação é a da primária — se dois fatos pedirem coisas diferentes, a mais
  // grave vence (596 antes de resumo), que é a mesma ordem de `fatos`.
  const acao = fatos.find((fato) => fato.acao)?.acao;
  return { tom, titulo: primeiro.titulo, paragrafos, acao };
}
