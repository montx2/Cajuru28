export type TipoDocumentoFiscal = "nfse" | "nfe" | "cte";
export type DirecaoDocumento = "tomada" | "prestada";
export type StatusDocumentoFiscal = "normal" | "cancelada";
/**
 * `aguardando` não é erro: é a SEFAZ pedindo a janela de 1 hora (cStat 656 ou
 * "nenhum documento novo"). O sistema reagenda sozinho — o operador não faz
 * nada e não deve ver vermelho.
 */
export type StatusExecucao = "em_andamento" | "aguardando" | "concluida" | "erro";
export type LeiauteDocumento = "completo" | "resumo";

export interface Empresa {
  id: number;
  razao_social: string;
  cnpj_cpf: string;
  uf: string;
  ativa: boolean;
  criado_em: string;
  sincronizar_automaticamente?: boolean;
  /** comma-separated: "nfse,nfe,cte" */
  quais_tipos_sincronizar?: string | null;
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
  em_andamento: boolean;
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
