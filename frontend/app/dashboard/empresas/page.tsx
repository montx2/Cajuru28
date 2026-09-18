"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { dataCurta, formatarCnpjCpf } from "@/lib/format";
import { BuscaInput, ChipsFiltro, ContadorLista } from "@/components/Busca";
import { Icone } from "@/components/icons";
import { Esqueleto, EstadoVazio } from "@/components/ui";
import type { ConsultaCNPJ, Empresa, LoteEmpresasResposta, ResumoCertificado } from "@/lib/types";

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

type FiltroCertificado = "todas" | "validos" | "vencendo" | "vencidos" | "sem";
type Ordenacao = "nome" | "recentes" | "vencimento";

const ORDENACOES: { id: Ordenacao; rotulo: string }[] = [
  { id: "nome", rotulo: "Nome (A–Z)" },
  { id: "recentes", rotulo: "Cadastro mais recente" },
  { id: "vencimento", rotulo: "Certificado por vencer" },
];

/** Coluna "Certificado": badge com o estado real do A1 da empresa. */
function SeloCertificadoEmpresa({ certificado }: { certificado?: ResumoCertificado }) {
  if (!certificado || !certificado.tem_certificado) {
    return (
      <span className="badge-danger" title="Nenhum certificado A1 enviado — a importação desta empresa fica bloqueada">
        sem certificado
      </span>
    );
  }
  if (certificado.vencido) {
    return (
      <span className="badge-danger" title={`Venceu em ${dataCurta(certificado.validade)}`}>
        vencido em {dataCurta(certificado.validade)}
      </span>
    );
  }
  if (certificado.vence_em_breve) {
    return (
      <span
        className="badge-warn"
        title={`Válido até ${dataCurta(certificado.validade)} — o A1 leva alguns dias para renovar`}
      >
        vence em {certificado.dias_para_vencer} d
      </span>
    );
  }
  return (
    <span className="badge-ok" title={`Válido até ${dataCurta(certificado.validade)}`}>
      válido até {dataCurta(certificado.validade)}
    </span>
  );
}

export default function EmpresasPage() {
  const { somenteLeitura } = usePapel();
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [certificados, setCertificados] = useState<ResumoCertificado[]>([]);
  const [carregando, setCarregando] = useState(true);

  // filtros da lista
  const [busca, setBusca] = useState("");
  const [filtroCert, setFiltroCert] = useState<FiltroCertificado>("todas");
  const [ufFiltro, setUfFiltro] = useState("");
  const [ordenacao, setOrdenacao] = useState<Ordenacao>("nome");

  // formulário de nova empresa
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
  const [excluindoId, setExcluindoId] = useState<number | null>(null);

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
    Promise.all([
      api.listarEmpresas(),
      api.resumoCertificados().catch(() => [] as ResumoCertificado[]),
    ])
      .then(([lista, resumo]) => {
        setEmpresas(lista);
        setCertificados(resumo);
      })
      .finally(() => setCarregando(false));
  }

  useEffect(carregar, []);

  const certPorEmpresa = useMemo(() => {
    const mapa = new Map<number, ResumoCertificado>();
    for (const item of certificados) mapa.set(item.empresa_id, item);
    return mapa;
  }, [certificados]);

  const ufsCadastradas = useMemo(
    () => [...new Set(empresas.map((empresa) => empresa.uf).filter(Boolean))].sort(),
    [empresas]
  );

  /** Contagens por estado de certificado, já considerando busca e UF. */
  const baseFiltrada = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const digitos = termo.replace(/\D/g, "");
    return empresas.filter((empresa) => {
      if (ufFiltro && empresa.uf !== ufFiltro) return false;
      if (!termo) return true;
      return (
        empresa.razao_social.toLowerCase().includes(termo) ||
        (digitos.length > 0 && empresa.cnpj_cpf.includes(digitos)) ||
        empresa.uf.toLowerCase() === termo
      );
    });
  }, [empresas, busca, ufFiltro]);

  const contagens = useMemo(() => {
    let validos = 0;
    let vencendo = 0;
    let vencidos = 0;
    let sem = 0;
    for (const empresa of baseFiltrada) {
      const cert = certPorEmpresa.get(empresa.id);
      if (!cert || !cert.tem_certificado) sem += 1;
      else if (cert.vencido) vencidos += 1;
      else if (cert.vence_em_breve) vencendo += 1;
      else validos += 1;
    }
    return { validos, vencendo, vencidos, sem, todas: baseFiltrada.length };
  }, [baseFiltrada, certPorEmpresa]);

  const visiveis = useMemo(() => {
    let lista = baseFiltrada;
    if (filtroCert === "validos")
      lista = lista.filter((empresa) => {
        const cert = certPorEmpresa.get(empresa.id);
        return cert?.tem_certificado && !cert.vencido && !cert.vence_em_breve;
      });
    else if (filtroCert === "vencendo")
      lista = lista.filter((empresa) => {
        const cert = certPorEmpresa.get(empresa.id);
        return cert?.tem_certificado && !cert.vencido && cert.vence_em_breve;
      });
    else if (filtroCert === "vencidos")
      lista = lista.filter((empresa) => certPorEmpresa.get(empresa.id)?.vencido);
    else if (filtroCert === "sem")
      lista = lista.filter((empresa) => {
        const cert = certPorEmpresa.get(empresa.id);
        return !cert?.tem_certificado;
      });

    const porNome = (a: Empresa, b: Empresa) => a.razao_social.localeCompare(b.razao_social, "pt-BR");
    if (ordenacao === "recentes") {
      return [...lista].sort((a, b) => (b.criado_em ?? "").localeCompare(a.criado_em ?? "") || porNome(a, b));
    }
    if (ordenacao === "vencimento") {
      return [...lista].sort((a, b) => {
        const dias = (empresa: Empresa) => {
          const cert = certPorEmpresa.get(empresa.id);
          if (!cert?.tem_certificado || cert.vencido) return 99999;
          return cert.dias_para_vencer ?? 99998;
        };
        return dias(a) - dias(b) || porNome(a, b);
      });
    }
    return [...lista].sort(porNome);
  }, [baseFiltrada, filtroCert, ordenacao, certPorEmpresa]);

  const filtrosAtivos =
    (busca.trim() ? 1 : 0) +
    (ufFiltro ? 1 : 0) +
    (filtroCert !== "todas" ? 1 : 0);

  function limparFiltros() {
    setBusca("");
    setUfFiltro("");
    setFiltroCert("todas");
  }

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

  async function excluirEmpresa(empresa: Empresa) {
    const confirmado = window.confirm(
      `Excluir ${empresa.razao_social}?\n\nTodos os XMLs, certificados e históricos desta empresa serão removidos definitivamente.`
    );
    if (!confirmado) return;
    setErro(null);
    setExcluindoId(empresa.id);
    try {
      await api.excluirEmpresa(empresa.id);
      setEmpresas((atuais) => atuais.filter((item) => item.id !== empresa.id));
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível excluir a empresa.");
    } finally {
      setExcluindoId(null);
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

  const opcoesFiltro = [
    { id: "todas", rotulo: "Todas", contador: contagens.todas },
    { id: "validos", rotulo: "A1 válido", contador: contagens.validos },
    { id: "vencendo", rotulo: "Vencendo", contador: contagens.vencendo },
    { id: "vencidos", rotulo: "Vencidos", contador: contagens.vencidos },
    { id: "sem", rotulo: "Sem certificado", contador: contagens.sem },
  ];

  return (
    <div className="animate-fade-up">
      <div className="page-header">
        <div>
          <p className="page-kicker">Base operacional</p>
          <h1 className="page-title">Empresas</h1>
          <p className="page-description">
            Cadastros, certificados e dados fiscais organizados para a automação trabalhar.
          </p>
        </div>
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
              <Icone nome="importacao" className="h-4 w-4" />
              {mostrarLote ? "Fechar importação" : "Importar em massa"}
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

          <div className="mt-4 rounded-xl border border-line bg-bg px-3 py-2.5 text-sm">
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
        <form onSubmit={importarLote} className="card-pad mb-6">
          <p className="mb-1 text-base font-medium text-ink">Importar empresas em massa</p>
          <p className="mb-4 text-sm text-ink-muted">
            Envie os certificados <span className="font-mono">.pfx</span>; CNPJ, razão social e UF são
            preenchidos automaticamente quando possível. Use CSV só para corrigir exceções
            (<span className="font-mono">razao_social;cnpj_cpf;uf[;senha]</span>).
          </p>

          <div className="mb-3 flex flex-wrap items-end gap-3">
            <div className="min-w-64 flex-1">
              <label className="label">Arquivos .pfx / .p12 (pode selecionar vários)</label>
              <input
                type="file"
                multiple
                accept=".pfx,.p12"
                onChange={(e) => setArquivos(Array.from(e.target.files ?? []))}
                className="text-sm text-ink"
              />
            </div>
            <div>
              <label className="label">CSV (opcional)</label>
              <input
                type="file"
                accept=".csv,.txt"
                onChange={(e) => setCsv(e.target.files?.[0] ?? null)}
                className="text-sm text-ink"
              />
            </div>
            <div>
              <label className="label">Senha dos certificados</label>
              <input
                type="password"
                value={senhaLote}
                onChange={(e) => setSenhaLote(e.target.value)}
                placeholder="senha comum (ou no CSV)"
                className="input"
              />
            </div>
            <div>
              <label className="label">UF fallback</label>
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
              <div className="table-shell">
                <table className="tabela">
                  <thead>
                    <tr>
                      <th>Origem</th>
                      <th>Empresa</th>
                      <th>CNPJ</th>
                      <th>UF</th>
                      <th>Situação</th>
                      <th>Detalhe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultadoLote.itens.map((item, indice) => (
                      <tr key={`${item.origem}-${indice}`}>
                        <td className="font-mono text-xs text-ink-muted">{item.origem}</td>
                        <td className="text-ink">{item.razao_social || "—"}</td>
                        <td className="font-mono text-ink-muted">{formatarCnpjCpf(item.cnpj_cpf)}</td>
                        <td className="font-mono text-ink-muted">{item.uf || "—"}</td>
                        <td>
                          <span
                            className={
                              item.status === "erro"
                                ? "badge-danger"
                                : item.status === "ja_existia"
                                  ? "badge-neutral"
                                  : "badge-ok"
                            }
                          >
                            {RÓTULO_STATUS_LOTE[item.status]}
                          </span>
                        </td>
                        <td className="text-xs text-ink-muted">
                          {item.status === "erro"
                            ? item.mensagem
                            : `${item.mensagem} — válido até ${dataCurta(item.validade)}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </form>
      )}

      {/* Barra de busca e filtros — a lista pode ter dezenas de empresas. */}
      {!carregando && empresas.length > 0 && (
        <div className="card mb-5 space-y-3 p-3 sm:p-4">
          <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center">
            <BuscaInput
              valor={busca}
              aoMudar={setBusca}
              placeholder="Buscar por razão social, CNPJ ou UF…"
              className="lg:max-w-md lg:flex-1"
              ariaLabel="Buscar empresa"
            />
            <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
              <select
                value={ufFiltro}
                onChange={(e) => setUfFiltro(e.target.value)}
                className="input h-10 w-auto"
                aria-label="Filtrar por UF"
              >
                <option value="">Todas as UFs</option>
                {ufsCadastradas.map((sigla) => (
                  <option key={sigla} value={sigla}>
                    UF {sigla}
                  </option>
                ))}
              </select>
              <select
                value={ordenacao}
                onChange={(e) => setOrdenacao(e.target.value as Ordenacao)}
                className="input h-10 w-auto"
                aria-label="Ordenar lista"
              >
                {ORDENACOES.map((opcao) => (
                  <option key={opcao.id} value={opcao.id}>
                    {opcao.rotulo}
                  </option>
                ))}
              </select>
              {filtrosAtivos > 0 && (
                <button type="button" onClick={limparFiltros} className="btn-ghost btn-sm">
                  <Icone nome="x" className="h-3.5 w-3.5" />
                  Limpar ({filtrosAtivos})
                </button>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <ChipsFiltro
              opcoes={opcoesFiltro}
              valor={filtroCert}
              aoMudar={(valor) => setFiltroCert(valor as FiltroCertificado)}
              rotuloGrupo="Filtrar empresas por certificado"
            />
            <ContadorLista visiveis={visiveis.length} total={empresas.length} rotulo="na lista" />
          </div>
        </div>
      )}

      {carregando ? (
        <div className="space-y-2">
          <Esqueleto className="h-14" />
          <Esqueleto className="h-14" />
          <Esqueleto className="h-14" />
        </div>
      ) : empresas.length === 0 ? (
        <EstadoVazio
          icone="empresa"
          titulo="Nenhuma empresa cadastrada"
          texto="Cadastre a primeira ou use “Importar em massa” para subir vários certificados de uma vez."
          acao={
            !somenteLeitura ? (
              <button type="button" onClick={() => setMostrarLote(true)} className="btn-primary btn-sm">
                Importar em massa
              </button>
            ) : undefined
          }
        />
      ) : visiveis.length === 0 ? (
        <EstadoVazio
          icone="busca"
          titulo="Nenhuma empresa encontrada"
          texto="Nenhuma empresa bate com a busca e os filtros atuais."
          acao={
            <button type="button" onClick={limparFiltros} className="btn-ghost btn-sm">
              Limpar busca e filtros
            </button>
          }
        />
      ) : (
        <div className="table-shell">
          <table className="tabela">
            <thead>
              <tr>
                <th>Empresa</th>
                <th className="hidden md:table-cell">UF</th>
                <th>Certificado A1</th>
                <th className="hidden lg:table-cell">Automação</th>
                <th className="hidden sm:table-cell">Cadastro</th>
                <th className="text-right">Ações</th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((empresa) => {
                const certificado = certPorEmpresa.get(empresa.id);
                return (
                  <tr key={empresa.id} className="group">
                    <td>
                      <Link href={`/dashboard/empresa?id=${empresa.id}`} className="block min-w-0">
                        <span className="block truncate font-semibold text-ink group-hover:text-accent-deep">
                          {empresa.razao_social}
                        </span>
                        <span className="mt-0.5 block font-mono text-xs text-ink-muted">
                          {formatarCnpjCpf(empresa.cnpj_cpf)}
                        </span>
                      </Link>
                    </td>
                    <td className="hidden font-mono text-ink-muted md:table-cell">{empresa.uf}</td>
                    <td>
                      <SeloCertificadoEmpresa certificado={certificado} />
                    </td>
                    <td className="hidden lg:table-cell">
                      {empresa.sincronizar_automaticamente === false ? (
                        <span className="badge-neutral" title="A varredura automática está desligada para esta empresa">
                          manual
                        </span>
                      ) : (
                        <span className="badge-ok" title="Varredura automática ligada">
                          automática
                        </span>
                      )}
                    </td>
                    <td className="hidden font-mono text-xs text-ink-muted sm:table-cell">
                      {dataCurta(empresa.criado_em)}
                    </td>
                    <td className="text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Link
                          href={`/dashboard/empresa?id=${empresa.id}`}
                          className="btn-ghost btn-sm"
                          title="Abrir cadastro, certificado e integrações"
                        >
                          Abrir
                        </Link>
                        {!somenteLeitura && (
                          <button
                            type="button"
                            onClick={() => excluirEmpresa(empresa)}
                            disabled={excluindoId === empresa.id}
                            className="btn-danger-ghost btn-sm"
                            title="Excluir a empresa e todos os seus XMLs"
                          >
                            {excluindoId === empresa.id ? "Excluindo…" : "Excluir"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!carregando && empresas.length > 0 && (
        <p className="mt-3 text-xs text-ink-muted">
          {contagens.validos + contagens.vencendo} empresa(s) aptas a importar ·{" "}
          {contagens.vencidos} com A1 vencido · {contagens.sem} sem certificado.{" "}
          <Link href="/dashboard/certificados" className="link">
            Gerenciar certificados →
          </Link>
        </p>
      )}
    </div>
  );
}
