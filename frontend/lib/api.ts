import { limparToken, obterToken } from "./auth";
import type {
  Certificado,
  DirecaoDocumento,
  DocumentoFiscal,
  Empresa,
  EmpresaResumoDocumentos,
  EstimativaExportacao,
  EstadoSincronizacao,
  ExecucaoImportacao,
  InfoSistema,
  ItemImportacaoLote,
  LoteEmpresasResposta,
  ResultadoImportacaoSelecionada,
  ResumoCertificado,
  ResumoDocumentos,
  ResumoSincronizacao,
  StatusDocumentoFiscal,
  TipoDocumentoFiscal,
} from "./types";

/**
 * Endereço da API.
 *
 * No Docker, `NEXT_PUBLIC_API_URL` é definido no build
 *   apontando para a API (ex.: `http://localhost:8000`).
 */
const BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }

  /**
   * 429 = "ainda não" (janela de consumo da SEFAZ), não "deu errado". A tela
   * mostra como aviso neutro e o sistema retoma sozinho na hora certa.
   */
  get ehAguardo(): boolean {
    return this.status === 429;
  }
}

async function chamar<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const token = obterToken();
  const cabecalhos: Record<string, string> = {
    ...(opcoes.body && !(opcoes.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const resposta = await fetch(`${BASE_URL}${caminho}`, { ...opcoes, headers: cabecalhos });

  if (resposta.status === 401) {
    limparToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada");
  }

  if (!resposta.ok) {
    const corpo = await resposta.json().catch(() => ({}));
    let detalhe = corpo.detail ?? "Erro inesperado na API";
    // FastAPI devolve lista de erros de validação Pydantic
    if (Array.isArray(detalhe)) {
      detalhe = detalhe
        .map((e: { msg?: string; loc?: unknown[] }) => e.msg ?? JSON.stringify(e))
        .join("; ");
    }
    throw new ApiError(resposta.status, typeof detalhe === "string" ? detalhe : "Erro na API");
  }

  if (resposta.status === 204) return undefined as T;
  return resposta.json();
}

function montarParams(filtros: object): string {
  const params = new URLSearchParams();
  for (const [chave, valor] of Object.entries(filtros as Record<string, unknown>)) {
    if (valor === undefined || valor === null || valor === "") continue;
    params.set(chave, String(valor));
  }
  const texto = params.toString();
  return texto ? `?${texto}` : "";
}

export interface FiltrosDocumentos {
  empresa_id?: number | null;
  /** "1,2,3" — omitir = todas as empresas do escritório */
  empresa_ids?: string;
  tipo?: TipoDocumentoFiscal;
  direcao?: DirecaoDocumento;
  status?: StatusDocumentoFiscal;
  /** MM/AAAA (o que a tela chama de "competência") */
  competencia?: string;
  leiaute?: "completo" | "resumo";
  busca?: string;
  limit?: number;
  offset?: number;
}

export interface FiltrosExportacao extends Omit<FiltrosDocumentos, "limit" | "offset" | "busca"> {
  incluir_canceladas?: boolean;
  incluir_relatorio?: boolean;
  /** seleção da tela ("baixar só estes"): ids separados por vírgula */
  documento_ids?: string;
}

async function baixarArquivo(caminho: string, nomePadrao: string): Promise<void> {
  const token = obterToken();
  const resposta = await fetch(`${BASE_URL}${caminho}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resposta.ok) {
    const corpo = await resposta.json().catch(() => ({}));
    throw new ApiError(
      resposta.status,
      typeof corpo?.detail === "string" ? corpo.detail : `Falha ao baixar ${nomePadrao}`
    );
  }
  const disposicao = resposta.headers.get("content-disposition") ?? "";
  const nomeReal = /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? nomePadrao;
  const url = URL.createObjectURL(await resposta.blob());
  const ancora = document.createElement("a");
  ancora.href = url;
  ancora.download = nomeReal;
  ancora.click();
  URL.revokeObjectURL(url);
}

export const api = {
  login: (email: string, senha: string) =>
    chamar<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, senha }),
    }),

  listarEmpresas: () => chamar<Empresa[]>("/empresas"),

  criarEmpresa: (razao_social: string, cnpj_cpf: string, uf: string) =>
    chamar<Empresa>("/empresas", { method: "POST", body: JSON.stringify({ razao_social, cnpj_cpf, uf }) }),

  atualizarEmpresa: (
    id: number,
    dados: Partial<
      Pick<Empresa, "razao_social" | "uf" | "ativa" | "sincronizar_automaticamente"> & {
        quais_tipos_sincronizar: string[];
      }
    >
  ) => chamar<Empresa>(`/empresas/${id}`, { method: "PATCH", body: JSON.stringify(dados) }),

  importarEmpresasEmMassa: (
    arquivos: File[],
    csv: File | null,
    senha: string,
    ufPadrao: string
  ) => {
    const form = new FormData();
    form.append("senha", senha);
    form.append("uf_padrao", ufPadrao);
    for (const arquivo of arquivos) form.append("arquivos", arquivo);
    if (csv) form.append("csv_arquivo", csv);
    return chamar<LoteEmpresasResposta>("/empresas/lote", { method: "POST", body: form });
  },

  obterEmpresa: (id: number) => chamar<Empresa>(`/empresas/${id}`),

  sincronizacaoDaEmpresa: (id: number) =>
    chamar<EstadoSincronizacao[]>(`/empresas/${id}/sincronizacao`),

  listarCertificados: (empresaId: number) =>
    chamar<Certificado[]>(`/certificados/empresa/${empresaId}`),

  /** Um certificado por empresa, com dias para vencer — alimenta o alerta. */
  resumoCertificados: () => chamar<ResumoCertificado[]>("/certificados/resumo"),

  enviarCertificado: (empresaId: number, senha: string, arquivo: File) => {
    const form = new FormData();
    form.append("empresa_id", String(empresaId));
    form.append("senha", senha);
    form.append("arquivo", arquivo);
    return chamar<Certificado>("/certificados", { method: "POST", body: form });
  },

  listarDocumentos: (filtros: FiltrosDocumentos = {}) =>
    chamar<DocumentoFiscal[]>(`/documentos${montarParams(filtros)}`),

  resumoPorEmpresa: (filtros: { competencia?: string; tipo?: TipoDocumentoFiscal } = {}) =>
    chamar<EmpresaResumoDocumentos[]>(`/documentos/por-empresa${montarParams(filtros)}`),

  resumoDocumentos: (filtros: { empresa_id?: number | null; competencia?: string } = {}) =>
    chamar<ResumoDocumentos>(`/documentos/resumo${montarParams(filtros)}`),

  urlXmlDocumento: (documentoId: number) => {
    // O browser precisa do token no header — para download simples abrimos
    // via fetch + blob em `baixarXmlDocumento`. Esta helper só monta a URL.
    return `${BASE_URL}/documentos/${documentoId}/xml`;
  },

  baixarXmlDocumento: (documentoId: number, nomeArquivo: string) =>
    baixarArquivo(`/documentos/${documentoId}/xml`, nomeArquivo),

  /** Quantos arquivos e quantos MB o "baixar tudo" vai dar, antes de baixar. */
  estimarExportacao: (filtros: FiltrosExportacao = {}) =>
    chamar<EstimativaExportacao>(`/documentos/exportar/estimativa${montarParams(filtros)}`),

  /** O download em massa: ZIP com todos os XMLs do filtro + relação em CSV. */
  baixarZip: (filtros: FiltrosExportacao = {}, nome?: string) =>
    baixarArquivo(
      `/documentos/exportar${montarParams(filtros)}`,
      nome ?? `NotasFlow_${filtros.competencia ?? "todos"}.zip`
    ),

  solicitarImportacao: (
    empresaId: number,
    tipo: TipoDocumentoFiscal,
    opcoes: { forcar?: boolean; competencia?: string } = {}
  ) =>
    chamar<ExecucaoImportacao>("/importacoes", {
      method: "POST",
      body: JSON.stringify({
        empresa_id: empresaId,
        tipo,
        forcar: opcoes.forcar ?? false,
        ...(opcoes.competencia ? { competencia: opcoes.competencia } : {}),
      }),
    }),

  solicitarImportacaoEmLote: (
    tipo: TipoDocumentoFiscal,
    opcoes: { competencia?: string; forcar?: boolean } = {}
  ) => {
    const params = new URLSearchParams({ tipo });
    if (opcoes.competencia) params.set("competencia", opcoes.competencia);
    if (opcoes.forcar) params.set("forcar", "true");
    return chamar<ItemImportacaoLote[]>(`/importacoes/lote?${params.toString()}`, { method: "POST" });
  },

  consultarExecucao: (id: number) => chamar<ExecucaoImportacao>(`/importacoes/${id}`),

  listarExecucoes: (empresaId?: number) =>
    chamar<ExecucaoImportacao[]>(
      `/importacoes${empresaId ? `?empresa_id=${empresaId}` : ""}`
    ),

  /** Painel de saúde: cursor, pendência e janela de cada empresa+tipo. */
  estadoSincronizacao: (empresaId?: number) =>
    chamar<EstadoSincronizacao[]>(
      `/importacoes/estado${empresaId ? `?empresa_id=${empresaId}` : ""}`
    ),

  resumoSincronizacao: () => chamar<ResumoSincronizacao>("/importacoes/resumo"),

  /** Busca o XML completo dos documentos que vieram só em resumo (consChNFe). */
  completarXmls: (empresaId?: number, limite = 20) =>
    chamar<{ disparado: boolean; aviso: string }>(
      `/documentos/completar-xmls${montarParams({ empresa_id: empresaId, limite })}`,
      { method: "POST" }
    ),

  // ---------------------------------------------------------------
  // Importar SÓ as empresas marcadas
  // ---------------------------------------------------------------
  // "Todas de uma vez" era o comportamento errado para o uso real: cada CNPJ
  // consultado gasta a janela de 1 hora da SEFAZ, e varrer quem não foi pedido
  // atrasa quem foi. A seleção é o padrão; marcar todas passa a ser a exceção.

  /** O que aconteceria ao disparar — sem disparar nada (só leitura local). */
  previaImportacaoSelecionadas: (dados: {
    empresa_ids: number[];
    tipos?: TipoDocumentoFiscal[];
    competencia?: string;
    forcar?: boolean;
  }) =>
    chamar<ResultadoImportacaoSelecionada>("/importacoes/selecionadas/previa", {
      method: "POST",
      body: JSON.stringify(dados),
    }),

  /** Dispara de verdade, apenas para as empresas marcadas. */
  importarSelecionadas: (dados: {
    empresa_ids: number[];
    tipos?: TipoDocumentoFiscal[];
    competencia?: string;
    forcar?: boolean;
  }) =>
    chamar<ResultadoImportacaoSelecionada>("/importacoes/selecionadas", {
      method: "POST",
      body: JSON.stringify(dados),
    }),

  // Diagnóstico do ambiente Docker.
  infoSistema: () => chamar<InfoSistema>("/sistema/info"),

  saudeDetalhada: () =>
    chamar<{
      ok: boolean;
      problemas: string[];
      banco_ok: boolean;
      disco_livre_bytes: number | null;
      pasta_dados: string;
    }>("/sistema/saude-detalhada"),
};
