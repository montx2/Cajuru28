import { limparToken, obterToken } from "./auth";
import type {
  Certificado,
  DocumentoFiscal,
  Empresa,
  ExecucaoImportacao,
  ItemImportacaoLote,
  TipoDocumentoFiscal,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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

export const api = {
  login: (email: string, senha: string) =>
    chamar<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, senha }),
    }),

  listarEmpresas: () => chamar<Empresa[]>("/empresas"),

  criarEmpresa: (razao_social: string, cnpj_cpf: string, uf: string) =>
    chamar<Empresa>("/empresas", { method: "POST", body: JSON.stringify({ razao_social, cnpj_cpf, uf }) }),

  obterEmpresa: (id: number) => chamar<Empresa>(`/empresas/${id}`),

  listarCertificados: (empresaId: number) =>
    chamar<Certificado[]>(`/certificados/empresa/${empresaId}`),

  enviarCertificado: (empresaId: number, senha: string, arquivo: File) => {
    const form = new FormData();
    form.append("empresa_id", String(empresaId));
    form.append("senha", senha);
    form.append("arquivo", arquivo);
    return chamar<Certificado>("/certificados", { method: "POST", body: form });
  },

  listarDocumentos: (
    empresaId: number,
    filtros?: { tipo?: TipoDocumentoFiscal; data_inicio?: string; data_fim?: string }
  ) => {
    const params = new URLSearchParams({ empresa_id: String(empresaId) });
    if (filtros?.tipo) params.set("tipo", filtros.tipo);
    if (filtros?.data_inicio) params.set("data_inicio", filtros.data_inicio);
    if (filtros?.data_fim) params.set("data_fim", filtros.data_fim);
    return chamar<DocumentoFiscal[]>(`/documentos?${params.toString()}`);
  },

  urlXmlDocumento: (documentoId: number) => {
    const token = obterToken();
    // O browser precisa do token no header — para download simples abrimos
    // via fetch + blob no caller. Esta helper só monta a URL.
    return `${BASE_URL}/documentos/${documentoId}/xml`;
  },

  baixarXmlDocumento: async (documentoId: number, nomeArquivo: string) => {
    const token = obterToken();
    const resposta = await fetch(`${BASE_URL}/documentos/${documentoId}/xml`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resposta.ok) throw new ApiError(resposta.status, "Falha ao baixar XML");
    const blob = await resposta.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nomeArquivo;
    a.click();
    URL.revokeObjectURL(url);
  },

  solicitarImportacao: (empresaId: number, tipo: TipoDocumentoFiscal, forcar = false) =>
    chamar<ExecucaoImportacao>("/importacoes", {
      method: "POST",
      body: JSON.stringify({ empresa_id: empresaId, tipo, forcar }),
    }),

  solicitarImportacaoEmLote: (tipo: TipoDocumentoFiscal) =>
    chamar<ItemImportacaoLote[]>(`/importacoes/lote?tipo=${tipo}`, { method: "POST" }),

  consultarExecucao: (id: number) => chamar<ExecucaoImportacao>(`/importacoes/${id}`),

  listarExecucoes: () => chamar<ExecucaoImportacao[]>("/importacoes"),
};
