import type {
  AgenteProcuracao,
  AlertasResposta,
  BackupsResposta,
  BackupRegistro,
  ConfiguracaoProcuracoes,
  CredencialAgente,
  CredencialIntegracao,
  Certificado,
  CertificadoPainel,
  ConferenciaCompetencia,
  ConsultaCNPJ,
  DirecaoDocumento,
  DetalheProcuracao,
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
  JobProcuracao,
  JobProcuracaoDetalhe,
  KpisDashboard,
  ListaProcuracoes,
  ModeloProcuracao,
  NotificacaoProcuracao,
  PassoRoteiro,
  ProcessarPendenciasResultado,
  RequisitosAgente,
  ResultadoSincronizacaoProcuracoes,
  ResumoProcuracoes,
  SituacaoOpcaoProcuracao,
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

/**
 * Endereço absoluto de um recurso da API, para uso em `href`/`src` — download
 * de evidência, por exemplo, precisa de navegação do próprio navegador (com
 * cookie de sessão), não de `fetch`.
 */
export function urlDaApi(caminho: string): string {
  return `${BASE_URL}${caminho.startsWith("/") ? caminho : `/${caminho}`}`;
}

/** Um campo recusado pela validação da API, já legível. */
export interface ProblemaValidacao {
  /** Nome do campo como o contrato o chama (`base_url`, `segredo`, …). */
  campo: string;
  mensagem: string;
}

export class ApiError extends Error {
  status: number;
  /**
   * Campos recusados, quando a API respondeu 422 com o array `detail` do
   * Pydantic. Guardar a estrutura (e não só a frase concatenada) é o que
   * permite a tela dizer *qual* campo está errado e destacá-lo.
   */
  problemas: ProblemaValidacao[];

  constructor(status: number, message: string, problemas: ProblemaValidacao[] = []) {
    super(message);
    this.status = status;
    this.problemas = problemas;
  }

  /**
   * 429 = "ainda não" (janela de consumo da SEFAZ), não "deu errado". A tela
   * mostra como aviso neutro e o sistema retoma sozinho na hora certa.
   */
  get ehAguardo(): boolean {
    return this.status === 429;
  }
}

export interface OpcoesChamada extends RequestInit {
  /**
   * Não redireciona para `/login` quando a API responder 401 — quem chamou
   * trata a ausência de sessão como resposta esperada, não como acidente.
   * É o caso da sondagem da própria tela de login.
   */
  silencioso?: boolean;
}

/** `/login` já é o destino: mandar para lá de novo só recarregaria a página. */
function naTelaDeLogin(): boolean {
  if (typeof window === "undefined") return false;
  const caminho = window.location.pathname;
  return caminho === "/login" || caminho.startsWith("/login/");
}

/**
 * Uma única navegação por sessão expirada.
 *
 * O shell dispara várias chamadas em paralelo (sessão, alertas, painel). Sem
 * esta trava, cada 401 da mesma rodada agendava seu próprio `replace` e o
 * navegador enfileirava recarregamentos concorrentes.
 */
let redirecionandoParaLogin = false;

async function chamar<T>(caminho: string, opcoes: OpcoesChamada = {}): Promise<T> {
  const { silencioso = false, ...init } = opcoes;
  const cabecalhos: Record<string, string> = {
    ...(init.body && !(init.body instanceof FormData)
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
      ...init,
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
    // Só navega quem está *fora* do login e não pediu silêncio. Redirecionar
    // para `/login` estando em `/login` recarrega a própria página: a sondagem
    // de sessão roda de novo, toma 401 de novo e o ciclo não para — era o
    // "pisca-pisca" que impedia digitar as credenciais.
    if (typeof window !== "undefined" && !silencioso && !naTelaDeLogin() && !redirecionandoParaLogin) {
      redirecionandoParaLogin = true;
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
    const problemas: ProblemaValidacao[] = [];
    // A localização vinda do Pydantic evita mensagens vagas em formulários extensos.
    if (Array.isArray(detalhe)) {
      for (const item of detalhe) {
        if (typeof item !== "object" || item === null) {
          problemas.push({ campo: "", mensagem: String(item) });
          continue;
        }
        const erro = item as { msg?: unknown; loc?: unknown[] };
        const campo = (erro.loc ?? [])
          .filter((parte) => parte !== "body" && parte !== "query" && parte !== "path")
          .join(" → ");
        // O Pydantic prefixa "Value error, " nas mensagens de validador
        // customizado; ela não acrescenta nada para quem está na tela.
        const mensagem = (typeof erro.msg === "string" ? erro.msg : "valor inválido").replace(
          /^Value error,\s*/i,
          ""
        );
        problemas.push({ campo, mensagem });
      }
      detalhe = problemas
        .map((item) => (item.campo ? `${item.campo}: ${item.mensagem}` : item.mensagem))
        .join("; ");
    }
    const mensagensStatus: Partial<Record<number, string>> = {
      403: "Origem não autorizada para esta sessão ou papel sem permissão para a ação.",
      413: "O arquivo ultrapassa o limite de 35 MiB. Selecione um arquivo menor.",
      429: "A consulta ainda está na janela de consumo. O sistema retoma automaticamente.",
    };
    const mensagem = mensagensStatus[resposta.status] ?? (typeof detalhe === "string" ? detalhe : "A API devolveu uma resposta inválida.");
    throw new ApiError(resposta.status, mensagem, problemas);
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
  leiaute?: "completo" | "resumo" | "metadados";
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

  /**
   * Mesma leitura, para quem já está no login: um 401 aqui é a resposta
   * esperada ("ainda não entrou"), então não dispara navegação nenhuma.
   */
  quemSouEuSilencioso: () => chamar<UsuarioAtual>("/auth/me", { silencioso: true }),

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
        | "manifestar_automaticamente"
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
      nome ?? `Fluxa_${filtros.data_inicio ?? "selecao"}.zip`
    ),

  baixarCsvDocumentos: (filtros: FiltrosExportacao = {}, nome?: string) =>
    baixarArquivo(
      `/documentos/exportar/csv${montarParams(filtros)}`,
      nome ?? `Fluxa_relacao_${filtros.data_inicio ?? "selecao"}.csv`
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
      `Fluxa_fechamento_${competencia ?? "mes"}.csv`
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

  /* ── Procurações RFB ───────────────────────────────────────────────────
   *
   * Leituras do painel, operação da fila e administração do módulo. A
   * execução no portal não passa por aqui: ela acontece na estação, conduzida
   * pelo Cajuru Agent, com o operador autenticando-se no ambiente oficial.
   */

  resumoProcuracoes: () => chamar<ResumoProcuracoes>("/procuracoes/resumo"),

  listarProcuracoes: (filtros: {
    situacao?: string;
    busca?: string;
    com_job?: boolean | null;
    pagina?: number;
    tamanho?: number;
  } = {}) => chamar<ListaProcuracoes>(`/procuracoes${montarParams(filtros)}`),

  situacoesProcuracao: () => chamar<SituacaoOpcaoProcuracao[]>("/procuracoes/situacoes"),

  detalheProcuracao: (empresaId: number) =>
    chamar<DetalheProcuracao>(`/procuracoes/empresas/${empresaId}`),

  roteiroProcuracao: (fase?: string) =>
    chamar<{ passos: PassoRoteiro[]; aviso: string }>(`/procuracoes/roteiro${montarParams({ fase })}`),

  listarJobsProcuracao: (filtros: { status?: string; empresa_id?: number; limite?: number } = {}) =>
    chamar<JobProcuracao[]>(`/procuracoes/jobs${montarParams(filtros)}`),

  jobProcuracao: (jobId: number) =>
    chamar<JobProcuracaoDetalhe>(`/procuracoes/jobs/${jobId}`),

  criarJobProcuracao: (empresa_id: number, opcoes: { forcar_nova_outorga?: boolean; modelo_id?: number | null } = {}) =>
    chamar<JobProcuracao>("/procuracoes/jobs", {
      method: "POST",
      body: JSON.stringify({ empresa_id, ...opcoes }),
    }),

  processarPendencias: (opcoes: { limite?: number; empresa_ids?: number[] } = {}) =>
    chamar<ProcessarPendenciasResultado>("/procuracoes/processar-pendencias", {
      method: "POST",
      body: JSON.stringify(opcoes),
    }),

  retomarJobProcuracao: (jobId: number) =>
    chamar<JobProcuracao>(`/procuracoes/jobs/${jobId}/retomar`, { method: "POST", body: "{}" }),

  cancelarJobProcuracao: (jobId: number, motivo: string) =>
    chamar<JobProcuracao>(`/procuracoes/jobs/${jobId}/cancelar`, {
      method: "POST",
      body: JSON.stringify({ motivo }),
    }),

  reprocessarJobProcuracao: (jobId: number) =>
    chamar<JobProcuracao>(`/procuracoes/jobs/${jobId}/reprocessar`, { method: "POST", body: "{}" }),

  intervencaoJobProcuracao: (jobId: number, motivo: string) =>
    chamar<JobProcuracao>(`/procuracoes/jobs/${jobId}/intervencao`, {
      method: "POST",
      body: JSON.stringify({ motivo }),
    }),

  // Registro manual: o operador concluiu no portal e informa o que o portal
  // devolveu. Sem protocolo ou texto de confirmação a API recusa.
  registrarOutorga: (jobId: number, dados: { protocolo?: string; confirmacao_portal?: string }) =>
    chamar<JobProcuracao>(`/procuracoes/jobs/${jobId}/registrar-outorga`, {
      method: "POST",
      body: JSON.stringify(dados),
    }),

  registrarAceite: (jobId: number, dados: { confirmacao_portal?: string }) =>
    chamar<JobProcuracao>(`/procuracoes/jobs/${jobId}/registrar-aceite`, {
      method: "POST",
      body: JSON.stringify(dados),
    }),

  configuracaoProcuracoes: () => chamar<ConfiguracaoProcuracoes>("/procuracoes/configuracao"),

  salvarConfiguracaoProcuracoes: (dados: Partial<ConfiguracaoProcuracoes>) =>
    chamar<ConfiguracaoProcuracoes>("/procuracoes/configuracao", {
      method: "PUT",
      body: JSON.stringify(dados),
    }),

  modelosProcuracao: () => chamar<ModeloProcuracao[]>("/procuracoes/modelos"),

  salvarModeloProcuracao: (dados: Partial<ModeloProcuracao> & { nome: string }, id?: number) =>
    chamar<ModeloProcuracao>(id ? `/procuracoes/modelos/${id}` : "/procuracoes/modelos", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(dados),
    }),

  excluirModeloProcuracao: (id: number) =>
    chamar<void>(`/procuracoes/modelos/${id}`, { method: "DELETE" }),

  integracoesProcuracao: () => chamar<CredencialIntegracao[]>("/procuracoes/integracoes"),

  salvarIntegracaoProcuracao: (dados: {
    fonte: string;
    base_url?: string;
    segredo?: string;
    identificador?: string;
    ativo?: boolean;
    opcoes?: Record<string, string>;
  }) =>
    chamar<CredencialIntegracao>("/procuracoes/integracoes", {
      method: "PUT",
      body: JSON.stringify(dados),
    }),

  removerIntegracaoProcuracao: (fonte: string) =>
    chamar<void>(`/procuracoes/integracoes/${fonte}`, { method: "DELETE" }),

  testarIntegracaoProcuracao: (fonte: string) =>
    chamar<{ ok: boolean; detalhe: string; codigo: string | null }>(
      `/procuracoes/integracoes/${fonte}/testar`,
      { method: "POST", body: "{}" }
    ),

  sincronizarProcuracoes: (fonte: string) =>
    chamar<ResultadoSincronizacaoProcuracoes>("/procuracoes/sincronizar", {
      method: "POST",
      body: JSON.stringify({ fonte }),
    }),

  importarPlanilhaProcuracoes: (
    arquivo: File,
    opcoes: { fonte?: string; situacaoPadrao?: string } = {}
  ) => {
    const corpo = new FormData();
    corpo.append("arquivo", arquivo);
    // Quem sabe de onde o arquivo veio é o operador: o mesmo CSV vale como
    // dado do Jettax (precedência maior) ou como planilha do escritório.
    corpo.append("fonte_declarada", opcoes.fonte ?? "planilha");
    corpo.append("situacao_padrao", opcoes.situacaoPadrao ?? "");
    return chamar<ResultadoSincronizacaoProcuracoes>("/procuracoes/importar-planilha", {
      method: "POST",
      body: corpo,
    });
  },

  /** Importa a lista copiada da tela do fornecedor (sem credencial nenhuma). */
  importarListaProcuracoes: (dados: {
    texto: string;
    fonte?: string;
    situacao_padrao?: string;
  }) =>
    chamar<ResultadoSincronizacaoProcuracoes>("/procuracoes/importar-lista", {
      method: "POST",
      body: JSON.stringify({
        texto: dados.texto,
        fonte: dados.fonte ?? "jettax360",
        situacao_padrao: dados.situacao_padrao ?? "",
      }),
    }),

  agentesProcuracao: () => chamar<AgenteProcuracao[]>("/procuracoes/agentes"),

  /**
   * Matrícula de estação. O identificador é gerado pelo servidor e volta na
   * resposta — só se informa aqui para **re-credenciar** uma estação que já
   * existe (mesma máquina, segredo novo).
   */
  matricularAgente: (nome: string, identificador?: string) =>
    chamar<CredencialAgente>("/procuracoes/agentes", {
      method: "POST",
      body: JSON.stringify({ nome, ...(identificador ? { identificador } : {}) }),
    }),

  revogarAgente: (id: number, motivo: string) =>
    chamar<AgenteProcuracao>(`/procuracoes/agentes/${id}/revogar`, {
      method: "POST",
      body: JSON.stringify({ motivo }),
    }),

  requisitosAgente: () => chamar<RequisitosAgente>("/procuracoes/agentes/requisitos"),

  notificacoesProcuracao: (apenasAbertas = true) =>
    chamar<NotificacaoProcuracao[]>(`/procuracoes/notificacoes${montarParams({ apenas_abertas: apenasAbertas })}`),

  reconhecerNotificacaoProcuracao: (id: number) =>
    chamar<NotificacaoProcuracao>(`/procuracoes/notificacoes/${id}/reconhecer`, {
      method: "POST",
      body: "{}",
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
