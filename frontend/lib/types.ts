export type TipoDocumentoFiscal = "nfse" | "nfe" | "cte";
export type DirecaoDocumento = "tomada" | "prestada";
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
}

export interface ExecucaoImportacao {
  id: number;
  empresa_id: number;
  tipo: TipoDocumentoFiscal;
  status: StatusExecucao;
  documentos_importados: number;
  iniciado_em: string;
  finalizado_em: string | null;
  empresa_razao_social: string | null;
}

export interface ItemImportacaoLote {
  empresa_id: number;
  razao_social: string;
  status: "enfileirada" | "em_cooldown" | "sem_certificado";
  execucao_id: number | null;
  disponivel_em: string | null;
}
