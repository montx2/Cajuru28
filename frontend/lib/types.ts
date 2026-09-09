export type TipoDocumentoFiscal = "nfse" | "nfe" | "cte";
export type DirecaoDocumento = "tomada" | "prestada";
export type StatusDocumentoFiscal = "normal" | "cancelada";
export type StatusExecucao = "em_andamento" | "concluida" | "erro";

export interface Empresa {
  id: number;
  razao_social: string;
  cnpj_cpf: string;
  uf: string;
  ativa: boolean;
  criado_em: string;
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
  valor_total: number;
  status: StatusDocumentoFiscal;
  motivo_cancelamento?: string | null;
  cancelado_em?: string | null;
}

export interface ResumoDocumentos {
  total: number;
  normais: number;
  canceladas: number;
  por_tipo: Record<string, number>;
}

export interface ExecucaoImportacao {
  id: number;
  empresa_id: number;
  tipo: TipoDocumentoFiscal;
  status: StatusExecucao;
  documentos_importados: number;
  documentos_cancelados: number;
  eventos_nao_reconhecidos: number;
  iniciado_em: string;
  finalizado_em: string | null;
  mensagem_erro?: string | null;
  aviso?: string | null;
  ultimo_nsu?: string | null;
  empresa_razao_social: string | null;
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

export interface ItemImportacaoLote {
  empresa_id: number;
  razao_social: string;
  status: "enfileirada" | "em_cooldown" | "sem_certificado";
  execucao_id: number | null;
  disponivel_em: string | null;
}
