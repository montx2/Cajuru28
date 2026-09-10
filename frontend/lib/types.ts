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
