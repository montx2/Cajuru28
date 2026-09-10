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
  sem_xml?: number;
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
