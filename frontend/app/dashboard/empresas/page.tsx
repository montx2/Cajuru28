"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import type { ConsultaCNPJ, Empresa, LoteEmpresasResposta } from "@/lib/types";

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

function formatarDocumento(valor: string): string {
  const digitos = (valor || "").replace(/\D/g, "");
  if (digitos.length === 14) {
    return digitos.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
  }
  if (digitos.length === 11) {
    return digitos.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, "$1.$2.$3-$4");
  }
  return valor;
}

export default function EmpresasPage() {
  const { somenteLeitura } = usePapel();
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [mostrarFormulario, setMostrarFormulario] = useState(false);
  const [razaoSocial, setRazaoSocial] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [uf, setUf] = useState("");
  const [ufManual, setUfManual] = useState(false);
  const [consultandoCnpj, setConsultandoCnpj] = useState(false);
  const [consultaCnpj, setConsultaCnpj] = useState<ConsultaCNPJ | null>(null);
  const [avisoCnpj, setAvisoCnpj] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  // estado do importador em massa
  const [mostrarLote, setMostrarLote] = useState(false);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [csv, setCsv] = useState<File | null>(null);
  const [senhaLote, setSenhaLote] = useState("");
  const [ufLote, setUfLote] = useState("");
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

  useEffect(() => {
    const documento = cnpj.replace(/\D/g, "");
    setConsultaCnpj(null);
    setAvisoCnpj(null);
    setConsultandoCnpj(false);

    if (documento.length === 11) {
      setUf("");
      setUfManual(true);
      setAvisoCnpj("CPF não permite consulta de UF. Informe manualmente.");
      return;
    }
    if (documento.length !== 14) {
      if (!documento) setUfManual(false);
      setUf("");
      return;
    }

    let cancelado = false;
    setUf("");
    setConsultandoCnpj(true);
    const timer = window.setTimeout(async () => {
      try {
        const dados = await api.consultarCnpj(documento);
        if (cancelado) return;
        setConsultaCnpj(dados);
        if (dados.encontrado && dados.uf) {
          setUf(dados.uf);
          setUfManual(false);
          setAvisoCnpj(`${dados.uf} encontrada automaticamente${dados.municipio ? ` · ${dados.municipio}` : ""}.`);
          if (!razaoSocial.trim() && dados.razao_social) {
            setRazaoSocial(dados.razao_social);
          }
        } else {
          setUfManual(true);
          setAvisoCnpj(dados.mensagem || "Não consegui buscar a UF. Informe manualmente.");
        }
      } catch (e) {
        if (!cancelado) {
          setUfManual(true);
          setAvisoCnpj(e instanceof ApiError ? e.message : "Não consegui buscar a UF. Informe manualmente.");
        }
      } finally {
        if (!cancelado) setConsultandoCnpj(false);
      }
    }, 450);

    return () => {
      cancelado = true;
      window.clearTimeout(timer);
    };
  }, [cnpj]);

  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSalvando(true);
    try {
      await api.criarEmpresa(razaoSocial, cnpj.replace(/\D/g, ""), uf || undefined);
      setRazaoSocial("");
      setCnpj("");
      setUf("");
      setUfManual(false);
      setConsultaCnpj(null);
      setAvisoCnpj(null);
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
        <form onSubmit={criar} className="card-pad mb-6 max-w-3xl">
          <p className="mb-4 text-base font-semibold text-ink">Nova empresa</p>
          <div className="grid gap-4 md:grid-cols-[220px_1fr]">
            <div>
              <label className="label">CNPJ / CPF</label>
              <input
                required
                value={cnpj}
                onChange={(e) => setCnpj(e.target.value)}
                placeholder="somente números"
                className="input font-mono"
              />
              <p className="mt-1 text-xs text-ink-faint">
                Ao informar CNPJ, buscamos razão social e UF automaticamente.
              </p>
            </div>
            <div>
              <label className="label">Razão social</label>
              <input
                value={razaoSocial}
                onChange={(e) => setRazaoSocial(e.target.value)}
                placeholder="preenchida pelo CNPJ quando disponível"
                className="input"
              />
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-line bg-bg px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-ink-muted">UF</span>
              {consultandoCnpj ? (
                <span className="badge-neutral">buscando…</span>
              ) : uf && !ufManual ? (
                <span className="badge-ok">{uf} automática</span>
              ) : (
                <span className="badge-warn">informe manualmente</span>
              )}
              {consultaCnpj?.fonte && <span className="text-xs text-ink-faint">via {consultaCnpj.fonte}</span>}
              <button
                type="button"
                onClick={() => setUfManual((valor) => !valor)}
                className="link ml-auto text-xs font-semibold"
              >
                {ufManual ? "ocultar UF" : "alterar UF"}
              </button>
            </div>
            {avisoCnpj && <p className="mt-1 text-xs text-ink-muted">{avisoCnpj}</p>}
            {ufManual && (
              <select value={uf} onChange={(e) => setUf(e.target.value)} className="input mt-3">
                <option value="">Selecione a UF</option>
                {UFS.map((sigla) => (
                  <option key={sigla} value={sigla}>
                    {sigla}
                  </option>
                ))}
              </select>
            )}
          </div>

          {erro && <p className="mt-3 text-sm text-danger">{erro}</p>}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="submit" disabled={salvando || consultandoCnpj} className="btn-primary">
              {salvando ? "Salvando…" : "Cadastrar"}
            </button>
            <button type="button" onClick={() => setMostrarFormulario(false)} className="btn-ghost">
              Cancelar
            </button>
          </div>
        </form>
      )}

      {mostrarLote && (
        <form onSubmit={importarLote} className="mb-6 border border-line bg-surface p-5">
          <p className="mb-1 text-base font-medium text-ink">Importar empresas em massa</p>
          <p className="mb-4 text-sm text-ink-muted">
            Envie os certificados <span className="font-mono">.pfx</span>; CNPJ, razão social e UF são
            preenchidos automaticamente quando possível. Use CSV só para corrigir exceções
            (<span className="font-mono">razao_social;cnpj_cpf;uf[;senha]</span>).
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
              <label className="mb-1 block text-sm text-ink-muted">UF fallback</label>
              <select value={ufLote} onChange={(e) => setUfLote(e.target.value)} className="input">
                <option value="">Automática</option>
                {UFS.map((sigla) => (
                  <option key={sigla} value={sigla}>
                    {sigla}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <p className="mb-3 text-xs text-ink-muted">
            A senha é usada só para abrir os certificados enviados. Se a UF não vier do CNPJ,
            informe no CSV ou escolha uma UF fallback para o lote.
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
        <div className="grid gap-3 lg:grid-cols-2">
          {empresas.map((empresa) => (
            <Link
              key={empresa.id}
              href={`/dashboard/empresa?id=${empresa.id}`}
              className="card-hover rounded-card border border-line bg-surface p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-ink">{empresa.razao_social}</p>
                  <p className="mt-1 font-mono text-xs text-ink-muted">
                    {formatarDocumento(empresa.cnpj_cpf)}
                  </p>
                </div>
                <span className="badge-neutral">{empresa.uf}</span>
              </div>
              <p className="mt-3 text-xs text-accent">Abrir cadastro →</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
