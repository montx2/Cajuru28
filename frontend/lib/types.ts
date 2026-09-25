export type TipoDocumentoFiscal = "nfse" | "nfe" | "cte";
export type DirecaoDocumento = "tomada" | "prestada";
export type StatusDocumentoFiscal = "normal" | "cancelada";
/**
 * `aguardando` não é erro: é a SEFAZ pedindo a janela de 1 hora (cStat 656 ou
 * "nenhum documento novo"). O sistema reagenda sozinho — o operador não faz
 * nada e não deve ver vermelho.
 */
export type StatusExecucao = "em_andamento" | "aguardando" | "concluida" | "erro";
export type LeiauteDocumento = "completo" | "resumo" | "metadados";

export interface Empresa {
  id: number;
  razao_social: string;
  cnpj_cpf: string;
  uf: string;
  ativa: boolean;
  criado_em: string;
  sincronizar_automaticamente?: boolean;
  /** Opt-in do evento 210210. Desligado por padrão: ato irreversível. */
  manifestar_automaticamente?: boolean;
  /** comma-separated: "nfse,nfe,cte" */
  quais_tipos_sincronizar?: string | null;
  /** Código IBGE municipal de 7 dígitos. */
  codigo_ibge?: string | null;
  /** Inscrição municipal/CCM. */
  inscricao_municipal?: string | null;
}

export interface ConsultaCNPJ {
  documento: string;
  encontrado: boolean;
  razao_social: string;
  nome_fantasia: string;
  uf: string;
  municipio: string;
  codigo_ibge: string;
  fonte: string;
  mensagem: string;
}

export interface Certificado {
  id: number;
  empresa_id: number;
  validade: string;
  ativo: boolean;
  criado_em: string;
}

export interface ResumoCertificado {
  empresa_id: number;
  razao_social: string;
  tem_certificado: boolean;
  validade: string | null;
  dias_para_vencer: number | null;
  /** true = já venceu (toda importação desta empresa vai falhar) */
  vencido: boolean;
  /** true = vence em até 30 dias (prazo real de renovação do A1) */
  vence_em_breve: boolean;
}

export interface DocumentoFiscal {
  id: number;
  empresa_id: number;
  tipo: TipoDocumentoFiscal;
  direcao: DirecaoDocumento;
  chave_acesso: string;
  data_emissao: string;
  /** mês-calendário do documento (AAAA-MM-DD), extraído do próprio XML */
  competencia?: string | null;
  valor_total: number;
  status: StatusDocumentoFiscal;
  motivo_cancelamento?: string | null;
  cancelado_em?: string | null;
  /** `resumo` = a SEFAZ ainda só devolveu o resumo oficial (resNFe) */
  leiaute?: LeiauteDocumento | string;
  numero?: string | null;
  serie?: string | null;
  emitente_nome?: string | null;
  emitente_documento?: string | null;
  destinatario_nome?: string | null;
  destinatario_documento?: string | null;
  nsu?: string | null;
  origem?: string | null;
  /** Quando a Ciência da Operação (210210) foi registrada na SEFAZ. */
  manifestado_em?: string | null;
  /** Motivo da recusa da SEFAZ (cStat + xMotivo) quando a Ciência falhou. */
  manifestacao_erro?: string | null;
}

export interface ResultadoExclusaoDocumentos {
  excluidos: number;
  ids: number[];
  arquivos_removidos: number;
}

export interface ResetGeralResposta {
  empresas: number;
  documentos: number;
  certificados: number;
  execucoes: number;
  sincronizacoes: number;
  arquivos_removidos: number;
  integracoes: number;
}

export interface ResumoDocumentos {
  total: number;
  normais: number;
  canceladas: number;
  por_tipo: Record<string, number>;
}

export interface EstimativaExportacao {
  documentos: number;
  empresas: number;
  periodo: string;
  estimado_bytes: number;
  limite: number;
}

export interface ExecucaoImportacao {
  id: number;
  empresa_id: number;
  tipo: TipoDocumentoFiscal;
  status: StatusExecucao;
  documentos_importados: number;
  documentos_cancelados: number;
  eventos_nao_reconhecidos: number;
  documentos_no_periodo: number;
  /** Recebidos fora do recorte, mas guardados para não perder o NSU. */
  documentos_fora_do_periodo: number;
  iniciado_em: string;
  finalizado_em: string | null;
  mensagem_erro?: string | null;
  aviso?: string | null;
  ultimo_nsu?: string | null;
  empresa_razao_social: string | null;
  data_inicio?: string | null;
  data_fim?: string | null;
  tentativas?: number;
  bloqueado_ate?: string | null;
  origem?: string;
  forcar?: boolean;
}

/** Uma linha por empresa+tipo: é o que responde "preciso clicar em algo?" */
export interface EstadoSincronizacao {
  empresa_id: number;
  razao_social: string;
  tipo: string;
  ultimo_nsu: string;
  max_nsu: string | null;
  pendencia: number;
  em_dia: boolean;
  bloqueado_ate: string | null;
  motivo_bloqueio: string | null;
  bloqueios_seguidos: number;
  proxima_consulta_em: string | null;
  ultima_consulta_em: string | null;
  /** quando a próxima consulta fica liberada (ISO); null = já liberado */
  liberacao_em: string | null;
  /** segundos que faltam até liberar (0 = já pode consultar) */
  segundos_para_liberar: number;
  /** frase pronta: "liberado", "libera em 42 min"… */
  liberacao_rotulo: string;
  em_andamento: boolean;
  /** `maxNSU` desconhecido: nunca consultado com sucesso (≠ em dia). */
  nunca_consultado?: boolean;
  travado: boolean;
  sincronizar_automaticamente: boolean;
  cota_pontual_disponivel: number;
  dias_sem_varrer: number | null;
  /** a distribuição só tem ~3 meses: parado esse tempo, o que falta pode ter saído */
  risco_documento_fora_da_distribuicao: boolean;
}

/** Resultado por empresa+tipo da importação por seleção. */
export interface ItemImportacaoSelecionada {
  empresa_id: number;
  razao_social: string;
  tipo: TipoDocumentoFiscal;
  /** ok (prévia) | enfileirada | em_cooldown | sem_certificado | sem_uf | ja_em_andamento | fila_indisponivel */
  status: string;
  execucao_id: number | null;
  disponivel_em: string | null;
  mensagem: string;
  enfileirada: boolean;
}

export interface ResultadoImportacaoSelecionada {
  total: number;
  enfileiradas: number;
  aguardando: number;
  ignoradas: number;
  itens: ItemImportacaoSelecionada[];
}

/** Novos status possíveis da prévia (antes de disparar). */
export const ROTULO_STATUS_SELECAO: Record<string, string> = {
  ok: "Pode rodar agora",
  enfileirada: "Enfileirada",
  em_cooldown: "Na janela de 1 h da SEFAZ",
  ja_em_andamento: "Já está varrendo",
  em_andamento: "Já está varrendo",
  sem_certificado: "Sem certificado A1",
  sem_uf: "Sem UF cadastrada",
  fila_indisponivel: "Fila indisponível",
  erro: "Falhou",
};

// ---------------------------------------------------------------
// Informações operacionais do ambiente Docker
// ---------------------------------------------------------------

export interface InfoSistema {
  modo: "docker";
  modo_desktop: false;
  modo_servidor: true;
  banco: "postgresql";
  dados_dir: string;
  fila: {
    modo: "celery";
    agenda: Record<string, { tarefa?: string }>;
  };
  hora_do_servidor: string;
  webhook?: {
    configurado: boolean;
    nivel_minimo: string;
    intervalo_minutos: number;
  };
}

export interface ResumoSincronizacao {
  empresas: number;
  combinacoes: number;
  em_dia: number;
  com_pendencia: number;
  em_andamento: number;
  aguardando_janela: number;
  bloqueadas_sefaz: number;
  documentos_no_banco: number;
  sincronismo_automatico: boolean;
  intervalo_minutos: number;
  tick_a_partir_de: string | null;
}

export interface ItemConferenciaCompetencia {
  empresa_id: number;
  razao_social: string;
  tipo: TipoDocumentoFiscal;
  status: string;
  documentos: number;
  canceladas: number;
  sem_xml_completo: number;
  ultimo_nsu: string | null;
  max_nsu: string | null;
  pendencia: number;
  ultima_consulta_em: string | null;
  proxima_consulta_em: string | null;
  bloqueado_ate: string | null;
  mensagem: string;
}

export interface ConferenciaCompetencia {
  competencia: string;
  inicio: string;
  fim: string;
  status: "completa" | "parcial" | "pendente" | "critico" | string;
  ok: boolean;
  mensagem: string;
  documentos: number;
  canceladas: number;
  sem_xml_completo: number;
  empresas: number;
  itens_total: number;
  itens_ok: number;
  itens_pendentes: number;
  itens_criticos: number;
  itens: ItemConferenciaCompetencia[];
}

export interface EmpresaResumoDocumentos {
  empresa_id: number;
  razao_social: string;
  total: number;
  normais: number;
  canceladas: number;
  /** Quantos ainda estão só com o resumo (`resNFe`) — o botão "completar XML". */
  sem_xml_completo: number;
  valor_total: number;
}

export type StatusItemLote =
  | "enfileirada"
  | "em_andamento"
  | "ja_em_andamento"
  | "em_cooldown"
  | "sem_certificado"
  | "sem_uf"
  | "fila_indisponivel"
  | "erro";

export interface ItemImportacaoLote {
  empresa_id: number;
  razao_social: string;
  status: StatusItemLote | string;
  execucao_id: number | null;
  disponivel_em: string | null;
  mensagem?: string;
}

export interface ItemLoteEmpresas {
  origem: string;
  cnpj_cpf: string;
  razao_social: string;
  uf: string;
  status: "criada" | "certificado_atualizado" | "ja_existia" | "erro";
  mensagem: string;
  empresa_id: number | null;
  certificado_id: number | null;
  validade: string | null;
}

export interface LoteEmpresasResposta {
  total: number;
  criadas: number;
  certificados: number;
  ja_existiam: number;
  erros: number;
  itens: ItemLoteEmpresas[];
}

export const ROTULO_TIPO: Record<TipoDocumentoFiscal, string> = {
  nfse: "NFS-e",
  nfe: "NFe",
  cte: "CT-e",
};

export const ROTULO_STATUS_LOTE: Record<string, string> = {
  enfileirada: "Enfileirada",
  em_andamento: "Já estava em andamento",
  ja_em_andamento: "Já estava em andamento",
  em_cooldown: "Aguardando a janela da SEFAZ",
  sem_certificado: "Sem certificado ativo",
  sem_uf: "UF não informada",
  fila_indisponivel: "Fila indisponível (Redis/Celery)",
  erro: "Falhou",
};

export const TIPOS: TipoDocumentoFiscal[] = ["nfse", "nfe", "cte"];

// ---------------------------------------------------------------
// Sessão
// ---------------------------------------------------------------

export type PapelUsuario = "admin" | "operador" | "leitura";

export interface UsuarioAtual {
  id: number;
  nome: string;
  email: string;
  papel: PapelUsuario | string;
  escritorio_id: number;
  escritorio_nome: string;
}

export interface Usuario {
  id: number;
  nome: string;
  email: string;
  papel: PapelUsuario | string;
  ativo: boolean;
  criado_em: string;
}

export interface RegistroAuditoria {
  id: number;
  quando: string;
  usuario_email: string;
  acao: string;
  entidade: string | null;
  entidade_id: number | null;
  detalhe: string | null;
}

export const ROTULO_PAPEL: Record<string, string> = {
  admin: "Administrador",
  operador: "Operador",
  leitura: "Somente leitura",
};

export const ROTULO_ACAO: Record<string, string> = {
  login: "Entrou no sistema",
  login_falha: "Tentativa de login falhou",
  empresa_criada: "Cadastrou empresa",
  empresa_atualizada: "Atualizou empresa",
  empresas_lote: "Importou empresas em massa",
  certificado_enviado: "Enviou certificado",
  importacao_disparada: "Disparou importação",
  importacao_lote: "Disparou importação em lote",
  importacao_selecao: "Disparou importação por seleção",
  cursor_rebobinado: "Rebobinou cursor de importação",
  xmls_completar: "Pediu XMLs completos",
  exportacao_zip: "Baixou ZIP",
  usuario_criado: "Criou usuário",
  usuario_atualizado: "Atualizou usuário",
  webhook_teste: "Testou webhook",
};

// ---------------------------------------------------------------
// Dashboard executivo
// ---------------------------------------------------------------

export interface KpisDashboard {
  competencia: string;
  documentos_mes: number;
  documentos_mes_anterior: number;
  variacao_pct: number | null;
  valor_mes: number;
  canceladas_mes: number;
  sem_xml_completo: number;
  documentos_total: number;
  empresas_total: number;
  empresas_em_dia: number;
  combinacoes_em_dia: number;
  combinacoes_total: number;
  certificados_vencidos: number;
  certificados_vencendo: number;
  empresas_sem_certificado: number;
  bloqueadas_agora: number;
  em_andamento: number;
}

export interface EvolucaoMensal {
  mes: string;
  rotulo: string;
  total: number;
  valor: number;
  nfse: number;
  nfe: number;
  cte: number;
}

export interface TipoBreakdown {
  tipo: TipoDocumentoFiscal;
  rotulo: string;
  total: number;
  valor: number;
  percentual: number;
}

export interface EmitenteTop {
  documento: string | null;
  nome: string | null;
  total: number;
  valor: number;
}

export interface EmpresaRanking {
  empresa_id: number;
  razao_social: string;
  total: number;
  valor: number;
  canceladas: number;
  sem_xml: number;
}

// ---------------------------------------------------------------
// Alertas
// ---------------------------------------------------------------

export type NivelAlerta = "critico" | "atencao" | "info";

export interface AlertaItem {
  id: string;
  nivel: NivelAlerta | string;
  categoria: string;
  titulo: string;
  detalhe: string;
  empresa_id: number | null;
  empresa_razao_social: string | null;
  acao_rotulo: string | null;
  acao_href: string | null;
}

export interface AlertasResposta {
  total: number;
  criticos: number;
  atencao: number;
  infos: number;
  itens: AlertaItem[];
}

export const ROTULO_CATEGORIA_ALERTA: Record<string, string> = {
  certificado: "Certificado",
  cadastro: "Cadastro",
  sefaz: "SEFAZ",
  distribuicao: "Distribuição",
  sincronismo: "Sincronismo",
  xml: "XML",
  execucao: "Execução",
  sistema: "Sistema",
};

// ---------------------------------------------------------------
// Fechamento mensal
// ---------------------------------------------------------------

export interface FechamentoTipo {
  qtd: number;
  valor: number;
}

export interface FechamentoEmpresa {
  empresa_id: number;
  razao_social: string;
  cnpj: string;
  uf: string;
  total: number;
  valor: number;
  canceladas: number;
  sem_xml: number;
  por_tipo: Record<string, FechamentoTipo>;
}

export interface FechamentoTotais {
  documentos: number;
  valor: number;
  canceladas: number;
  sem_xml: number;
  empresas_com_documento: number;
  empresas_total: number;
  por_tipo: Record<string, FechamentoTipo>;
}

export interface FechamentoMensal {
  competencia: string;
  inicio: string;
  fim: string;
  totais: FechamentoTotais;
  empresas: FechamentoEmpresa[];
}

// ---------------------------------------------------------------
// Documento detalhado (drawer)
// ---------------------------------------------------------------

export interface DocumentoDetalhe extends DocumentoFiscal {
  empresa_razao_social: string;
  empresa_cnpj: string;
  empresa_uf: string;
  importado_em: string | null;
  xml_disponivel: boolean;
  xml_bytes: number | null;
  execucao_id: number | null;
}

// ---------------------------------------------------------------
// Painel operacional — a tela "está tudo funcionando?"
// ---------------------------------------------------------------

export type StatusGeral = "operando" | "atencao" | "critico";

export interface PainelEmpresas {
  cadastradas: number;
  ativas: number;
  habilitadas_sincronizacao: number;
  sincronizadas_hoje: number;
  em_dia: number;
  aguardando_janela: number;
  com_erro_24h: number;
  sem_certificado: number;
}

export interface PainelCertificados {
  validos: number;
  vencendo: number;
  vencidos: number;
}

export interface PainelExecucoes {
  em_andamento: number;
  aguardando: number;
  bloqueadas: number;
  concluidas_hoje: number;
  erros_24h: number;
  duracao_media_minutos: number | null;
}

export interface PainelDocumentos {
  hoje: number;
  cancelados_hoje: number;
  total: number;
  aguardando_xml_completo: number;
  mes: number;
  valor_mes: number;
  competencia: string;
}

export interface ComponenteStatus {
  nome: string;
  status: "ok" | "atencao" | "erro" | "desconhecido" | "desligado" | string;
  detalhe: string;
}

export interface UltimaSincronizacao {
  empresa_id: number;
  razao_social: string;
  tipo: string;
  status: string;
  documentos: number;
  finalizado_em: string | null;
  iniciado_em: string | null;
  mensagem_erro: string | null;
  aviso: string | null;
}

export interface PainelOperacional {
  status_geral: StatusGeral | string;
  mensagem: string;
  alertas: { criticos: number; atencao: number; info: number };
  empresas: PainelEmpresas;
  certificados: PainelCertificados;
  execucoes: PainelExecucoes;
  documentos: PainelDocumentos;
  componentes: ComponenteStatus[];
  ultimas_sincronizacoes: UltimaSincronizacao[];
}

export interface ExecucaoAoVivo {
  execucao_id: number;
  empresa_id: number;
  razao_social: string;
  tipo: string;
  status: string;
  documentos_importados: number;
  ultimo_nsu: string | null;
  iniciado_em: string | null;
  aguardando_ate: string | null;
  motivo_espera: string | null;
  aviso: string | null;
  mensagem_erro: string | null;
}

export interface JanelaProximaConsulta {
  empresa_id: number;
  razao_social: string;
  tipo: string;
  proxima_consulta_em: string;
  bloqueada: boolean;
  pendencia: number;
}

export interface CentralExecucoes {
  agora: ExecucaoAoVivo[];
  proximas: JanelaProximaConsulta[];
  recentes: ExecucaoImportacao[];
  erros: ExecucaoImportacao[];
}

// ---------------------------------------------------------------
// Centro de certificados
// ---------------------------------------------------------------

export interface CertificadoPainel extends ResumoCertificado {
  ultima_utilizacao_em: string | null;
  ultima_validacao_em: string | null;
  ultimo_erro: string | null;
  cnpj_cpf: string;
}

// ---------------------------------------------------------------
// Backup / saúde do sistema
// ---------------------------------------------------------------

export interface BackupRegistro {
  id: number;
  tipo: string;
  status: "ok" | "erro" | "em_andamento" | string;
  iniciado_em: string;
  finalizado_em: string | null;
  tamanho_bytes: number | null;
  empresas: number;
  documentos: number;
  execucoes: number;
  detalhe: string | null;
  erro: string | null;
  restauracao_testada_em: string | null;
  restauracao_ok: boolean | null;
}

export interface SaudeBackup {
  ativo: boolean;
  ultimo_ok_em: string | null;
  ultimo_ok_tamanho_bytes: number | null;
  horas_desde_ultimo_ok: number | null;
  ultimo_teste_em: string | null;
  ultimo_teste_ok: boolean | null;
  proximo_previsto_em: string | null;
  retencao: number;
  atrasado: boolean;
  total_registros: number;
  erros_recentes: number;
  tamanho_total_bytes: number;
}

export interface BackupsResposta {
  saude: SaudeBackup;
  registros: BackupRegistro[];
}

/* ── Procurações RFB ─────────────────────────────────────────────────────── */

/**
 * Espelho fiel de `backend/app/procuracoes/esquemas.py`. Campo que não existe
 * lá não existe aqui: tipo otimista vira `undefined` em produção e a tela
 * mostra "—" sem ninguém entender por quê.
 */

export type SituacaoAutorizacao =
  | "sem_autorizacao"
  | "em_analise"
  | "aguardando_aceite"
  | "ativa"
  | "expirada"
  | "cancelada"
  | "rejeitada"
  | "erro"
  | "intervencao_manual";

export interface ResumoProcuracoes {
  total_empresas: number;
  sem_autorizacao: number;
  em_analise: number;
  aguardando_aceite: number;
  ativas: number;
  expiradas: number;
  /** Ativas que vencem dentro da janela configurada de alerta. */
  vencendo: number;
  canceladas: number;
  jobs_na_fila: number;
  jobs_aguardando_humano: number;
  jobs_com_erro: number;
  jobs_concluidos_24h: number;
  agentes_online: number;
  agentes_total: number;
  agentes_com_assinador: number;
  certificados_disponiveis: number;
  certificados_vencendo: number;
  notificacoes_abertas: number;
  duracao_media_minutos: number;
  taxa_sucesso: number;
}

export interface LinhaProcuracao {
  empresa_id: number;
  razao_social: string;
  documento: string;
  uf: string;
  situacao: SituacaoAutorizacao | string;
  data_validade: string | null;
  dias_para_vencer: number | null;
  /** Relógio dos 30 dias; só vem preenchido enquanto o aceite está pendente. */
  prazo_aceite_ate: string | null;
  dias_para_aceite: number | null;
  outorgado_documento: string;
  protocolo: string;
  origem_dado: string;
  sincronizado_em: string | null;
  job_id: number | null;
  job_status: string;
  job_etapa: string;
  job_modo: string;
  job_atualizado_em: string | null;
  certificado_disponivel: boolean;
  servicos: number;
}

export interface ListaProcuracoes {
  itens: LinhaProcuracao[];
  total: number;
  pagina: number;
  tamanho: number;
}

export interface EventoJobProcuracao {
  id: number;
  job_id: number;
  quando: string | null;
  tipo: string;
  etapa: string;
  status_anterior: string;
  status_novo: string;
  mensagem: string;
  codigo_erro: string;
  ator: string;
  /** Nome resolvido pelo backend ("Ana", "Estação PC Fiscal 01", "Sistema"). */
  ator_rotulo: string;
  /** Presente quando quem provocou foi uma pessoa — a tela mostra "você". */
  usuario_id: number | null;
}

export interface EvidenciaJob {
  id: number;
  etapa: string;
  tipo: string;
  sha256: string;
  tamanho_bytes: number;
  url_observada: string;
  criado_em: string | null;
}

export interface PassoRoteiro {
  etapa: string;
  fase: string;
  titulo: string;
  instrucao: string;
  url: string;
  confirmacao: string;
  executor: "operador" | "sistema";
  certificado: "cliente" | "contabilidade";
}

export interface JobProcuracao {
  id: number;
  status: string;
  fase: string;
  etapa_atual: string;
  modo: string;
  tentativas: number;
  codigo_erro: string;
  classe_erro: string;
  mensagem_erro: string;
  motivo_intervencao: string;
  criado_em: string | null;
  iniciado_em: string | null;
  finalizado_em: string | null;
  agente_id: number | null;
  vigencia_ate: string | null;
  protocolo: string;
}

export interface JobProcuracaoDetalhe extends JobProcuracao {
  empresa_id: number;
  empresa_nome: string;
  empresa_documento: string;
  escopo_servicos: string;
  servicos: Array<Record<string, string>>;
  outorgado_documento: string;
  outorgado_nome: string;
  certificado_thumbprint: string;
  proxima_tentativa_em: string | null;
  eventos: EventoJobProcuracao[];
  evidencias: EvidenciaJob[];
  roteiro: PassoRoteiro[];
}

export interface CertificadoInventario {
  id: number;
  agente_id: number;
  thumbprint: string;
  titular_nome: string;
  documento: string;
  valido_ate: string | null;
  situacao: string;
  tipo: string;
}

export interface DetalheProcuracao {
  empresa: LinhaProcuracao;
  permissoes: Array<{ codigo: string; rotulo: string }>;
  jobs: JobProcuracao[];
  eventos: EventoJobProcuracao[];
  certificados: CertificadoInventario[];
}

export interface AgenteProcuracao {
  id: number;
  identificador: string;
  nome: string;
  hostname: string;
  usuario_windows: string;
  sistema_operacional: string;
  versao_agente: string;
  versao_navegador: string;
  versao_assinador: string;
  assinador_ok: boolean;
  assinador_detalhe: string;
  jobs_em_andamento: number;
  ativo: boolean;
  revogado_em: string | null;
  revogado_motivo: string;
  ultimo_heartbeat_em: string | null;
  criado_em: string | null;
  situacao: "online" | "processando" | "offline" | "revogado" | string;
  certificados: number;
}

/** Só existe na resposta da matrícula: o segredo não volta em nenhuma leitura. */
export interface CredencialAgente {
  agente: AgenteProcuracao;
  segredo: string;
  aviso: string;
}

export interface ConfiguracaoProcuracoes {
  id: number;
  outorgado_documento: string;
  outorgado_nome: string;
  modo_padrao: "assistido" | "consulta_api" | "nao_assistido";
  modo_efetivo: string;
  fundamento_politica: string;
  processamento_automatico: boolean;
  sincronizacao_automatica: boolean;
  hora_sincronizacao: number;
  intervalo_entre_jobs_segundos: number;
  max_jobs_simultaneos: number;
  max_jobs_por_agente: number;
  max_tentativas: number;
  timeout_etapa_segundos: number;
  timeout_job_segundos: number;
  heartbeat_tolerancia_segundos: number;
  alerta_dias: string;
  assinador_versao_minima: string;
  assinador_exigido: boolean;
  autorizacao_formal_rfb: boolean;
  autorizacao_formal_referencia: string;
  atualizado_em: string | null;
}

export interface ModeloProcuracao {
  id: number;
  nome: string;
  descricao: string;
  vigencia_meses: number;
  escopo_servicos: string;
  padrao: boolean;
  ativo: boolean;
  servicos: Array<{ codigo: string; rotulo: string }>;
  criado_em: string | null;
  atualizado_em: string | null;
}

export interface CredencialIntegracao {
  fonte: string;
  rotulo: string;
  base_url: string;
  identificador: string;
  configurado: boolean;
  ativo: boolean;
  opcoes: Record<string, unknown>;
  ultima_utilizacao_em: string | null;
  ultimo_erro: string;
  atualizado_em: string | null;
}

export interface PassoRequisitoAgente {
  chave: string;
  titulo: string;
  acao: string;
}

/**
 * Resposta de `GET /procuracoes/agentes/requisitos`.
 *
 * O nome do campo é `assinador`, não `passos`: o cliente declarava `passos` e
 * a tela de Estações quebrava (`undefined.slice`) justamente quando havia
 * estação sem Assinador apto — o único momento em que o roteiro aparece.
 */
export interface RequisitosAgente {
  assinador: PassoRequisitoAgente[];
  url_local: string;
  manual: string;
  verificacao_oficial: string;
}

export interface PendenciaImportacao {
  documento: string;
  /** Nome como a fonte escreveu — é o que permite reconhecer o cliente. */
  nome?: string;
  codigo: string;
  mensagem: string;
}

export interface ResultadoSincronizacaoProcuracoes {
  fonte: string;
  recebidos: number;
  criados: number;
  atualizados: number;
  inalterados: number;
  ignorados: number;
  invalidos: number;
  mensagem: string;
  erros: PendenciaImportacao[];
}

export interface ProcessarPendenciasResultado {
  avaliadas: number;
  criados: number;
  ja_na_fila: number;
  ignoradas: number;
  bloqueados_por_certificado: number;
  motivos: Record<string, number>;
  job_ids: number[];
}

export interface NotificacaoProcuracao {
  id: number;
  tipo: string;
  nivel: string;
  titulo: string;
  detalhe: string;
  empresa_id: number | null;
  job_id: number | null;
  criado_em: string | null;
  reconhecida_em: string | null;
}

export interface SituacaoOpcaoProcuracao {
  valor: SituacaoAutorizacao;
  rotulo: string;
}
