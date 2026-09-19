import type {
  AlertasResposta,
  BackupsResposta,
  BackupRegistro,
  Certificado,
  CertificadoPainel,
  ConferenciaCompetencia,
  ConsultaCNPJ,
  DirecaoDocumento,
  DocumentoDetalhe,
  DocumentoFiscal,
  Empresa,
  EmpresaRanking,
  EmpresaResumoDocumentos,
  EmitenteTop,
  EstimativaExportacao,
  EstadoSincronizacao,
  EvolucaoMensal,
  ExecucaoImportacao,
  FechamentoMensal,
  InfoSistema,
  ItemImportacaoLote,
  JettaxConfiguracaoEmpresa,
  JettaxExecucao,
  KpisDashboard,
  LoteEmpresasResposta,
  PainelOperacional,
  CentralExecucoes,
  RegistroAuditoria,
  ResetGeralResposta,
  ResultadoExclusaoDocumentos,
  ResultadoImportacaoSelecionada,
  ResumoCertificado,
  ResumoDocumentos,
  ResumoSincronizacao,
  StatusDocumentoFiscal,
  TipoBreakdown,
  TipoDocumentoFiscal,
  Usuario,
  UsuarioAtual,
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
  const cabecalhos: Record<string, string> = {
    ...(opcoes.body && !(opcoes.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
  };

  // O próprio login é público: um 401 aqui significa "senha errada", não
  // "sessão expirada". Sem esta distinção o tratamento genérico abaixo
  // limpava o token e recarregava /login, engolindo o motivo real.
  const ehLogin = caminho.startsWith("/auth/login");

  let resposta: Response;
  try {
    resposta = await fetch(`${BASE_URL}${caminho}`, {
      ...opcoes,
      credentials: "include",
      headers: cabecalhos,
    });
  } catch {
    // fetch só lança em falha de rede/CORS — a API não respondeu. Sem este
    // catch a tela dizia apenas "tente novamente", escondendo que o
    // problema é o contêiner da API fora do ar.
    throw new ApiError(
      0,
      `Não foi possível falar com a API em ${BASE_URL || "(mesma origem)"}. ` +
        `Verifique se os contêineres estão rodando (docker compose ps) e se a API responde em ${
          BASE_URL || "http://localhost:8000"
        }/saude.`
    );
  }

  if (resposta.status === 401 && !ehLogin) {
    if (typeof window !== "undefined") {
      // Leva o caminho atual: depois de entrar, o operador volta à tela em que
      // estava em vez de cair sempre no painel. `replace` não deixa a página
      // expirada no histórico — o "voltar" não repete o 401.
      const atual = `${window.location.pathname}${window.location.search}`;
      const destino = atual.startsWith("/dashboard") ? `?destino=${encodeURIComponent(atual)}` : "";
      window.location.replace(`/login${destino}`);
    }
    throw new ApiError(401, "Sessão expirada");
  }

  if (!resposta.ok) {
    const corpo = await resposta.json().catch(() => ({}));
    let detalhe: unknown = corpo.detail ?? "Erro inesperado na API";
    // A localização vinda do Pydantic evita mensagens vagas em formulários extensos.
    if (Array.isArray(detalhe)) {
      detalhe = detalhe
        .map((item: unknown) => {
          if (typeof item !== "object" || item === null) return String(item);
          const erro = item as { msg?: unknown; loc?: unknown[] };
          const local = erro.loc?.filter((parte) => parte !== "body").join(" → ");
          const mensagem = typeof erro.msg === "string" ? erro.msg : "valor inválido";
          return local ? `${local}: ${mensagem}` : mensagem;
        })
        .join("; ");
    }
    const mensagensStatus: Partial<Record<number, string>> = {
      403: "Origem não autorizada para esta sessão ou papel sem permissão para a ação.",
      413: "O arquivo ultrapassa o limite de 35 MiB. Selecione um arquivo menor.",
      429: "A consulta ainda está na janela de consumo. O sistema retoma automaticamente.",
    };
    const mensagem = mensagensStatus[resposta.status] ?? (typeof detalhe === "string" ? detalhe : "A API devolveu uma resposta inválida.");
    throw new ApiError(resposta.status, mensagem);
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
  /**
   * Período — **obrigatório** em toda consulta ao acervo (a API responde 422
   * sem ele). Em AAAA-MM-DD, que é o formato do `<input type="date">`.
   * Exceção única: o download por seleção (`documento_ids`), em que o operador
   * já escolheu nota a nota.
   */
  data_inicio?: string;
  data_fim?: string;
  /** Atalho opcional para o mês inteiro (MM/AAAA). O intervalo vence quando os dois vêm. */
  competencia?: string;
  leiaute?: "completo" | "resumo";
  busca?: string;
  numero?: string;
  serie?: string;
  emitente_documento?: string;
  destinatario_documento?: string;
  origem?: string;
  valor_min?: number | string;
  valor_max?: number | string;
  limit?: number;
  offset?: number;
}

export interface FiltrosExportacao extends Omit<FiltrosDocumentos, "limit" | "offset"> {
  incluir_canceladas?: boolean;
  incluir_relatorio?: boolean;
  /** seleção da tela ("baixar só estes"): ids separados por vírgula */
  documento_ids?: string;
}

async function baixarArquivo(caminho: string, nomePadrao: string): Promise<void> {
  const resposta = await fetch(`${BASE_URL}${caminho}`, { credentials: "include" });
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
    chamar<{ autenticado: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, senha }),
    }),

  logout: () => chamar<void>("/auth/logout", { method: "POST" }),

  quemSouEu: () => chamar<UsuarioAtual>("/auth/me"),

  listarEmpresas: () => chamar<Empresa[]>("/empresas"),

  consultarCnpj: (cnpj: string) => chamar<ConsultaCNPJ>(`/empresas/consulta-cnpj/${cnpj}`),

  criarEmpresa: (razao_social: string, cnpj_cpf: string, uf?: string) =>
    chamar<Empresa>("/empresas", {
      method: "POST",
      body: JSON.stringify({ razao_social, cnpj_cpf, ...(uf ? { uf } : {}) }),
    }),

  atualizarEmpresa: (
    id: number,
    dados: Partial<
      Pick<
        Empresa,
        | "razao_social"
        | "uf"
        | "ativa"
        | "sincronizar_automaticamente"
        | "codigo_ibge"
        | "inscricao_municipal"
      > & {
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

  excluirEmpresa: (id: number) => chamar<void>(`/empresas/${id}`, { method: "DELETE" }),

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

  resumoPorEmpresa: (filtros: Omit<FiltrosDocumentos, "limit" | "offset" | "empresa_id" | "empresa_ids"> = {}) =>
    chamar<EmpresaResumoDocumentos[]>(`/documentos/por-empresa${montarParams(filtros)}`),

  resumoDocumentos: (filtros: Omit<FiltrosDocumentos, "limit" | "offset"> = {}) =>
    chamar<ResumoDocumentos>(`/documentos/resumo${montarParams(filtros)}`),

  urlXmlDocumento: (documentoId: number) => {
    // A sessão fica no cookie HttpOnly. Downloads autenticados devem usar
    // `baixarXmlDocumento`, que envia credentials: include via fetch.
    return `${BASE_URL}/documentos/${documentoId}/xml`;
  },

  baixarXmlDocumento: (documentoId: number, nomeArquivo: string) =>
    baixarArquivo(`/documentos/${documentoId}/xml`, nomeArquivo),

  excluirDocumento: (documentoId: number) =>
    chamar<ResultadoExclusaoDocumentos>(`/documentos/${documentoId}`, { method: "DELETE" }),

  excluirDocumentos: (ids: number[]) =>
    chamar<ResultadoExclusaoDocumentos>("/documentos/excluir-lote", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  /** Quantos arquivos e quantos MB o "baixar tudo" vai dar, antes de baixar. */
  estimarExportacao: (filtros: FiltrosExportacao = {}) =>
    chamar<EstimativaExportacao>(`/documentos/exportar/estimativa${montarParams(filtros)}`),

  /** O download em massa: ZIP com todos os XMLs do filtro + relação em CSV. */
  baixarZip: (filtros: FiltrosExportacao = {}, nome?: string) =>
    baixarArquivo(
      `/documentos/exportar${montarParams(filtros)}`,
      nome ?? `NotasFlow_${filtros.data_inicio ?? "selecao"}.zip`
    ),

  baixarCsvDocumentos: (filtros: FiltrosExportacao = {}, nome?: string) =>
    baixarArquivo(
      `/documentos/exportar/csv${montarParams(filtros)}`,
      nome ?? `NotasFlow_relacao_${filtros.data_inicio ?? "selecao"}.csv`
    ),

  /** O período (data_inicio/data_fim) é obrigatório: é ele que define o que será guardado. */
  solicitarImportacao: (
    empresaId: number,
    tipo: TipoDocumentoFiscal,
    opcoes: { forcar?: boolean; data_inicio: string; data_fim: string }
  ) =>
    chamar<ExecucaoImportacao>("/importacoes", {
      method: "POST",
      body: JSON.stringify({
        empresa_id: empresaId,
        tipo,
        forcar: opcoes.forcar ?? false,
        data_inicio: opcoes.data_inicio,
        data_fim: opcoes.data_fim,
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

  conferirCompetencia: (filtros: {
    competencia?: string;
    empresa_ids?: string;
    tipos?: string;
  } = {}) => chamar<ConferenciaCompetencia>(`/importacoes/conferencia${montarParams(filtros)}`),

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
    data_inicio: string;
    data_fim: string;
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
    data_inicio: string;
    data_fim: string;
    forcar?: boolean;
  }) =>
    chamar<ResultadoImportacaoSelecionada>("/importacoes/selecionadas", {
      method: "POST",
      body: JSON.stringify(dados),
    }),

  // ---------------------------------------------------------------
  // Dashboard executivo
  // ---------------------------------------------------------------

  kpis: (competencia?: string) =>
    chamar<KpisDashboard>(`/dashboard/kpis${montarParams({ competencia })}`),

  evolucao: (meses = 12) => chamar<EvolucaoMensal[]>(`/dashboard/evolucao${montarParams({ meses })}`),

  porTipo: (competencia?: string) =>
    chamar<TipoBreakdown[]>(`/dashboard/por-tipo${montarParams({ competencia })}`),

  topEmitentes: (competencia?: string, limite = 8) =>
    chamar<EmitenteTop[]>(`/dashboard/top-emitentes${montarParams({ competencia, limite })}`),

  rankingEmpresas: (competencia?: string, limite = 8) =>
    chamar<EmpresaRanking[]>(`/dashboard/ranking-empresas${montarParams({ competencia, limite })}`),

  atividades: (limite = 12) => chamar<ExecucaoImportacao[]>(`/dashboard/atividades${montarParams({ limite })}`),

  // ---------------------------------------------------------------
  // Alertas
  // ---------------------------------------------------------------

  alertas: () => chamar<AlertasResposta>("/alertas"),

  contagemAlertas: () => chamar<{ total: number; criticos: number; atencao: number }>("/alertas/contagem"),

  // ---------------------------------------------------------------
  // Fechamento mensal
  // ---------------------------------------------------------------

  fechamento: (competencia?: string) =>
    chamar<FechamentoMensal>(`/relatorios/fechamento${montarParams({ competencia })}`),

  baixarFechamentoCsv: (competencia?: string) =>
    baixarArquivo(
      `/relatorios/fechamento.csv${montarParams({ competencia })}`,
      `NotasFlow_fechamento_${competencia ?? "mes"}.csv`
    ),

  // ---------------------------------------------------------------
  // Equipe (só admin)
  // ---------------------------------------------------------------

  listarUsuarios: () => chamar<Usuario[]>("/usuarios"),

  criarUsuario: (dados: { nome: string; email: string; senha: string; papel: string }) =>
    chamar<Usuario>("/usuarios", { method: "POST", body: JSON.stringify(dados) }),

  atualizarUsuario: (
    id: number,
    dados: Partial<{ nome: string; email: string; senha: string; papel: string; ativo: boolean }>
  ) => chamar<Usuario>(`/usuarios/${id}`, { method: "PATCH", body: JSON.stringify(dados) }),

  // ---------------------------------------------------------------
  // Auditoria (admin e operador)
  // ---------------------------------------------------------------

  auditoria: (filtros: { acao?: string; busca?: string; limite?: number } = {}) =>
    chamar<RegistroAuditoria[]>(`/auditoria${montarParams(filtros)}`),

  acoesAuditoria: () => chamar<string[]>("/auditoria/acoes"),

  // Integração Acessórias: credencial cifrada e cadastro por CNPJ.
  statusAcessorias: () => chamar<{ configurado: boolean; base_url: string; ultima_sincronizacao_em: string | null }>("/integracoes/acessorias"),
  salvarCredencialAcessorias: (token: string, base_url: string) => chamar<{ configurado: boolean }>("/integracoes/acessorias/credencial", { method: "PUT", body: JSON.stringify({ token, base_url }) }),
  testarAcessorias: () => chamar<{ ok: boolean; mensagem: string }>("/integracoes/acessorias/testar", { method: "POST" }),
  sincronizarEmpresasAcessorias: () => chamar<{ recebidas: number; criadas: number; atualizadas: number; ignoradas: number; invalidas: number }>("/integracoes/acessorias/sincronizar-empresas", { method: "POST", body: JSON.stringify({ atualizar_existentes: true, somente_ativas: true }) }),

  // Integração Jettax (o token enviado nunca volta ao navegador).
  statusJettax: () => chamar<{ configurado: boolean; base_url: string; saude: string; mensagem?: string; empresas_registradas: number; empresas_ativas: number }>("/integracoes/jettax"),
  salvarCredencialJettax: (token: string, base_url: string) =>
    chamar<{ configurado: boolean; base_url: string }>("/integracoes/jettax/credencial", {
      method: "PUT", body: JSON.stringify({ token, base_url }),
    }),
  removerCredencialJettax: () => chamar<void>("/integracoes/jettax/credencial", { method: "DELETE" }),
  testarJettax: () => chamar<{ status: string; mensagem: string }>("/integracoes/jettax/testar", { method: "POST" }),
  obterJettaxEmpresa: (empresaId: number) =>
    chamar<JettaxConfiguracaoEmpresa>(`/integracoes/jettax/empresas/${empresaId}`),
  salvarJettaxEmpresa: (
    empresaId: number,
    dados: Partial<Pick<JettaxConfiguracaoEmpresa, "ativa" | "baixar_nfes" | "baixar_nfes_enviadas">>
  ) =>
    chamar<JettaxConfiguracaoEmpresa>(`/integracoes/jettax/empresas/${empresaId}`, {
      method: "PUT",
      body: JSON.stringify(dados),
    }),
  registrarJettaxEmpresa: (empresaId: number, enviar_certificado = false) =>
    chamar<JettaxConfiguracaoEmpresa>(`/integracoes/jettax/empresas/${empresaId}/registrar`, {
      method: "POST",
      body: JSON.stringify({ enviar_certificado }),
    }),
  atualizarClienteJettaxEmpresa: (empresaId: number, enviar_certificado = false) =>
    chamar<JettaxConfiguracaoEmpresa>(`/integracoes/jettax/empresas/${empresaId}/registrar`, {
      method: "PUT",
      body: JSON.stringify({ enviar_certificado }),
    }),
  importarNFSeJettax: (empresaId: number, filtros: { period?: string } = {}) =>
    chamar<JettaxExecucao>(`/integracoes/jettax/empresas/${empresaId}/importar/nfse`, {
      method: "POST",
      body: JSON.stringify(filtros),
    }),
  importarNFeJettax: (
    empresaId: number,
    dados: { direcao: "sales" | "purchases"; data_inicial?: string; data_final?: string }
  ) =>
    chamar<JettaxExecucao>(`/integracoes/jettax/empresas/${empresaId}/importar/nfe`, {
      method: "POST",
      body: JSON.stringify(dados),
    }),
  listarExecucoesJettaxEmpresa: (empresaId: number, limite = 20) =>
    chamar<JettaxExecucao[]>(`/integracoes/jettax/empresas/${empresaId}/execucoes${montarParams({ limite })}`),

  // ---------------------------------------------------------------
  // Webhook (teste manual, só admin)
  // ---------------------------------------------------------------

  testarWebhook: () =>
    chamar<{ ok: boolean; detalhe: string }>("/alertas/testar-webhook", { method: "POST" }),

  // ---------------------------------------------------------------
  // Documento detalhado + XML como texto (visualizador)
  // ---------------------------------------------------------------

  detalheDocumento: (id: number) => chamar<DocumentoDetalhe>(`/documentos/detalhe/${id}`),

  obterXmlTexto: async (id: number): Promise<string> => {
    const resposta = await fetch(`${BASE_URL}/documentos/${id}/xml`, {
      credentials: "include",
    });
    if (!resposta.ok) throw new ApiError(resposta.status, "Não foi possível ler o XML.");
    return resposta.text();
  },

  // Diagnóstico do ambiente Docker.
  infoSistema: () => chamar<InfoSistema>("/sistema/info"),

  resetGeral: (opcoes: { confirmar: string; remover_integracoes?: boolean; forcar?: boolean }) =>
    chamar<ResetGeralResposta>(
      `/sistema/reset-geral${montarParams({
        confirmar: opcoes.confirmar,
        remover_integracoes: opcoes.remover_integracoes ?? false,
        forcar: opcoes.forcar ?? false,
      })}`,
      { method: "POST" }
    ),

  // ---------------------------------------------------------------
  // Painel operacional (a primeira tela do operador)
  // ---------------------------------------------------------------

  painelOperacional: () => chamar<PainelOperacional>("/painel/operacional"),

  centralExecucoes: (limite = 30) =>
    chamar<CentralExecucoes>(`/painel/execucoes${montarParams({ limite })}`),

  // Centro de certificados: validade + telemetria de uso de cada A1.
  painelCertificados: () => chamar<CertificadoPainel[]>("/certificados/painel"),

  // Saúde do sistema + histórico de backups.
  backups: () => chamar<BackupsResposta>("/sistema/backups"),

  executarBackup: () =>
    chamar<BackupRegistro>("/sistema/backup", { method: "POST" }),

  testarBackup: (id: number) =>
    chamar<{ ok: boolean; detalhe: string }>(`/sistema/backups/${id}/testar`, {
      method: "POST",
    }),

  saudeDetalhada: () =>
    chamar<{
      ok: boolean;
      problemas: string[];
      banco_ok: boolean;
      disco_livre_bytes: number | null;
      pasta_dados: string;
    }>("/sistema/saude-detalhada"),
};
