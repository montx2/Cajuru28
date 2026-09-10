"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import type { Empresa, LoteEmpresasResposta } from "@/lib/types";

const UFS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
  "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
  "SP", "SE", "TO",
];

const RÓTULO_STATUS_LOTE: Record<LoteEmpresasResposta["itens"][number]["status"], string> = {
  criada: "Empresa criada",
  certificado_atualizado: "Certificado vinculado",
  ja_existia: "Já cadastrada",
  erro: "Erro",
};

function formatarData(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR");
}

export default function EmpresasPage() {
  const { somenteLeitura } = usePapel();
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [mostrarFormulario, setMostrarFormulario] = useState(false);
  const [razaoSocial, setRazaoSocial] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [uf, setUf] = useState("SP");
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  // estado do importador em massa
  const [mostrarLote, setMostrarLote] = useState(false);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [csv, setCsv] = useState<File | null>(null);
  const [senhaLote, setSenhaLote] = useState("");
  const [ufLote, setUfLote] = useState("SP");
  const [enviandoLote, setEnviandoLote] = useState(false);
  const [erroLote, setErroLote] = useState<string | null>(null);
  const [resultadoLote, setResultadoLote] = useState<LoteEmpresasResposta | null>(null);

  function carregar() {
    setCarregando(true);
    api
      .listarEmpresas()
      .then(setEmpresas)
      .finally(() => setCarregando(false));
  }

  useEffect(carregar, []);

  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSalvando(true);
    try {
      await api.criarEmpresa(razaoSocial, cnpj.replace(/\D/g, ""), uf);
      setRazaoSocial("");
      setCnpj("");
      setMostrarFormulario(false);
      carregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível cadastrar a empresa.");
    } finally {
      setSalvando(false);
    }
  }

  async function importarLote(evento: React.FormEvent) {
    evento.preventDefault();
    if (arquivos.length === 0 && !csv) return;
    setErroLote(null);
    setResultadoLote(null);
    setEnviandoLote(true);
    try {
      const resultado = await api.importarEmpresasEmMassa(arquivos, csv, senhaLote, ufLote);
      setResultadoLote(resultado);
      setArquivos([]);
      setCsv(null);
      setSenhaLote("");
      carregar();
    } catch (e) {
      setErroLote(e instanceof ApiError ? e.message : "Não foi possível importar o lote.");
    } finally {
      setEnviandoLote(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <p className="font-serif text-2xl text-ink">Empresas</p>
        {somenteLeitura ? (
          <span className="badge-neutral">perfil somente leitura</span>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => {
                setMostrarLote((v) => !v);
                setMostrarFormulario(false);
              }}
              className="btn-primary"
            >
              {mostrarLote ? "Fechar" : "Importar em massa"}
            </button>
            <button
              onClick={() => {
                setMostrarFormulario((v) => !v);
                setMostrarLote(false);
              }}
              className="btn-ghost"
            >
              {mostrarFormulario ? "Cancelar" : "Nova empresa"}
            </button>
          </div>
        )}
      </div>

      {mostrarFormulario && (
        <form onSubmit={criar} className="mb-6 border border-line bg-surface p-5">
          <div className="mb-3 flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-sm text-ink-muted">Razão social</label>
              <input
                required
                value={razaoSocial}
                onChange={(e) => setRazaoSocial(e.target.value)}
                className="w-full input"
              />
            </div>
            <div className="w-56">
              <label className="mb-1 block text-sm text-ink-muted">CNPJ / CPF</label>
              <input
                required
                value={cnpj}
                onChange={(e) => setCnpj(e.target.value)}
                placeholder="Somente números"
                className="w-full border border-line bg-bg px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent"
              />
            </div>
            <div className="w-24">
              <label className="mb-1 block text-sm text-ink-muted">UF</label>
              <select
                value={uf}
                onChange={(e) => setUf(e.target.value)}
                className="w-full input"
              >
                {UFS.map((sigla) => (
                  <option key={sigla} value={sigla}>
                    {sigla}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {erro && <p className="mb-3 text-sm text-danger">{erro}</p>}
          <button
            type="submit"
            disabled={salvando}
            className="btn-primary disabled:opacity-50"
          >
            {salvando ? "Salvando…" : "Cadastrar empresa"}
          </button>
        </form>
      )}

      {mostrarLote && (
        <form onSubmit={importarLote} className="mb-6 border border-line bg-surface p-5">
          <p className="mb-1 text-base font-medium text-ink">Importar empresas em massa</p>
          <p className="mb-4 text-sm text-ink-muted">
            Envie vários certificados <span className="font-mono">.pfx</span> de uma vez: o CNPJ e a
            razão social são lidos de dentro de cada certificado e a empresa é criada
            automaticamente. O CSV é opcional (colunas{" "}
            <span className="font-mono">razao_social;cnpj_cpf;uf[;senha]</span>) e serve para
            cadastrar empresas sem certificado ou indicar senha por arquivo.
          </p>

          <div className="mb-3 flex flex-wrap items-end gap-3">
            <div className="min-w-64 flex-1">
              <label className="mb-1 block text-sm text-ink-muted">
                Arquivos .pfx / .p12 (pode selecionar vários)
              </label>
              <input
                type="file"
                multiple
                accept=".pfx,.p12"
                onChange={(e) => setArquivos(Array.from(e.target.files ?? []))}
                className="text-sm text-ink"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-ink-muted">CSV (opcional)</label>
              <input
                type="file"
                accept=".csv,.txt"
                onChange={(e) => setCsv(e.target.files?.[0] ?? null)}
                className="text-sm text-ink"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-ink-muted">Senha dos certificados</label>
              <input
                type="password"
                value={senhaLote}
                onChange={(e) => setSenhaLote(e.target.value)}
                placeholder="senha comum (ou no CSV)"
                className="input"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-ink-muted">UF padrão</label>
              <select
                value={ufLote}
                onChange={(e) => setUfLote(e.target.value)}
                className="input"
              >
                {UFS.map((sigla) => (
                  <option key={sigla} value={sigla}>
                    {sigla}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <p className="mb-3 text-xs text-ink-muted">
            O sistema usa a senha que você informa para abrir cada certificado — não há tentativa
            automática de outras senhas. Arquivos com senha diferente aparecem no resultado como
            erro e não impedem o restante do lote.
          </p>
          {erroLote && <p className="mb-3 text-sm text-danger">{erroLote}</p>}
          <button
            type="submit"
            disabled={enviandoLote || (arquivos.length === 0 && !csv)}
            className="btn-primary disabled:opacity-50"
          >
            {enviandoLote
              ? "Importando…"
              : `Importar ${arquivos.length > 0 ? `${arquivos.length} certificado(s)` : "CSV"}`}
          </button>

          {resultadoLote && (
            <div className="mt-5">
              <p className="mb-2 text-sm text-ink">
                <span className="font-medium">{resultadoLote.criadas}</span> criadas ·{" "}
                <span className="font-medium">{resultadoLote.certificados}</span> certificados
                vinculados · <span className="font-medium">{resultadoLote.ja_existiam}</span> já
                cadastradas · <span className="font-medium">{resultadoLote.erros}</span> erros
              </p>
              <table className="w-full border-t border-line text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-ink-muted">
                    <th className="py-2 font-normal">Origem</th>
                    <th className="py-2 font-normal">Empresa</th>
                    <th className="py-2 font-normal">CNPJ</th>
                    <th className="py-2 font-normal">UF</th>
                    <th className="py-2 font-normal">Situação</th>
                    <th className="py-2 font-normal">Detalhe</th>
                  </tr>
                </thead>
                <tbody>
                  {resultadoLote.itens.map((item, indice) => (
                    <tr key={`${item.origem}-${indice}`} className="border-b border-line last:border-0">
                      <td className="py-2 font-mono text-xs text-ink-muted">{item.origem}</td>
                      <td className="py-2 text-ink">{item.razao_social || "—"}</td>
                      <td className="py-2 font-mono text-ink-muted">{item.cnpj_cpf || "—"}</td>
                      <td className="py-2 font-mono text-ink-muted">{item.uf || "—"}</td>
                      <td className="py-2">
                        <span
                          className={
                            item.status === "erro"
                              ? "text-danger"
                              : item.status === "ja_existia"
                                ? "text-ink-muted"
                                : "text-accent"
                          }
                        >
                          {RÓTULO_STATUS_LOTE[item.status]}
                        </span>
                      </td>
                      <td className="py-2 text-xs text-ink-muted">
                        {item.status === "erro"
                          ? item.mensagem
                          : `${item.mensagem} — válido até ${formatarData(item.validade)}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </form>
      )}

      {carregando ? (
        <p className="text-sm text-ink-muted">Carregando…</p>
      ) : empresas.length === 0 ? (
        <div className="border border-line bg-surface p-8 text-center">
          <p className="text-sm text-ink-muted">
            Nenhuma empresa cadastrada ainda. Cadastre a primeira ou use “Importar em massa” para
            subir vários certificados de uma vez.
          </p>
        </div>
      ) : (
        <table className="w-full border-t border-line text-sm">
          <thead>
            <tr className="border-b border-line text-left text-ink-muted">
              <th className="py-2 font-normal">Razão social</th>
              <th className="py-2 font-normal">CNPJ / CPF</th>
              <th className="py-2 font-normal">UF</th>
              <th className="py-2 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {empresas.map((empresa) => (
              <tr key={empresa.id} className="border-b border-line last:border-0">
                <td className="py-3 text-ink">{empresa.razao_social}</td>
                <td className="py-3 font-mono text-ink-muted">{empresa.cnpj_cpf}</td>
                <td className="py-3 font-mono text-ink-muted">{empresa.uf}</td>
                <td className="py-3 text-right">
                  <Link href={`/dashboard/empresa?id=${empresa.id}`} className="text-accent hover:underline">
                    abrir
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
