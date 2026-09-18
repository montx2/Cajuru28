"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type {
  Empresa,
  EstadoSincronizacao,
  ResumoCertificado,
  TipoDocumentoFiscal,
} from "@/lib/types";
import { dataCurta, formatarCnpjCpf } from "@/lib/format";
import { BuscaInput, ChipsFiltro } from "./Busca";
import { Icone } from "./icons";

/**
 * Lista de empresas para escolher de quem puxar as notas — a peça que
 * substitui o "importar de todas".
 *
 * Por que isso existe: cada consulta à SEFAZ queima a janela de 1 hora *daquele
 * CNPJ*. Varrer 60 empresas quando o contador precisa de 3 não é só trabalho
 * jogado fora: atrasa justamente as 3 que importam, porque todas disputam as
 * mesmas horas do dia. Selecionar é a operação correta; "todas" virou apenas o
 * caso em que a pessoa marca todas.
 *
 * Regras da lista:
 * - **Somente empresas com certificado A1 válido são selecionáveis.** É a
 *   pré-condição da consulta na SEFAZ; oferecer a escolha de uma empresa que
 *   vai falhar na hora é design que promete o que não entrega.
 * - As demais continuam visíveis (filtros "Vencidos" e "Sem certificado"),
 *   com o motivo e o atalho para resolver — sem certificado não é motivo para
 *   a empresa sumir do mapa.
 * - A busca fica sempre disponível: com 5 empresas ela não atrapalha; com 60
 *   ela é a diferença entre achar em 2 segundos e rolar a tela procurando.
 *
 * A seleção fica guardada no navegador: quem trabalha sempre com as mesmas 5
 * empresas não remarca a cada abertura do painel.
 */

const CHAVE_ARMAZENADA = "notasflow_empresas_selecionadas";

export type FiltroSeletor = "prontas" | "vencidos" | "sem" | "todas";

export function lerSelecaoSalva(): Set<number> {
  if (typeof window === "undefined") return new Set();
  try {
    const bruto = window.localStorage.getItem(CHAVE_ARMAZENADA);
    if (!bruto) return new Set();
    const lista = JSON.parse(bruto);
    return new Set(Array.isArray(lista) ? lista.filter((x) => typeof x === "number") : []);
  } catch {
    return new Set();
  }
}

function salvarSelecao(ids: Set<number>): void {
  try {
    window.localStorage.setItem(CHAVE_ARMAZENADA, JSON.stringify([...ids]));
  } catch {
    /* modo privado do navegador: seguir sem guardar não quebra nada */
  }
}

export function useSelecaoEmpresas(empresas: Empresa[]) {
  const [selecionadas, setSelecionadas] = useState<Set<number>>(new Set());
  const [carregado, setCarregado] = useState(false);

  // A primeira leitura precisa acontecer no cliente (localStorage não existe
  // no build estático) e depois que a lista de empresas chegou, para descartar
  // ids de empresas que não existem mais.
  useEffect(() => {
    if (carregado || empresas.length === 0) return;
    const salvas = lerSelecaoSalva();
    const existentes = new Set(empresas.map((empresa) => empresa.id));
    setSelecionadas(new Set([...salvas].filter((id) => existentes.has(id))));
    setCarregado(true);
  }, [empresas, carregado]);

  useEffect(() => {
    if (carregado) salvarSelecao(selecionadas);
  }, [selecionadas, carregado]);

  return { selecionadas, setSelecionadas, carregado };
}

/** Situação do certificado de uma empresa, para badge e para agrupamento. */
function grupoCertificado(
  certificado: ResumoCertificado | undefined,
  carregado: boolean
): "pronta" | "vencendo" | "vencido" | "sem" | "desconhecido" {
  // Resumo ainda não chegou (carregando ou falhou): sem mentir para o
  // operador, também sem travar a tela — segue selecionável como antes.
  if (!carregado) return "desconhecido";
  if (!certificado || !certificado.tem_certificado) return "sem";
  if (certificado.vencido) return "vencido";
  if (certificado.vence_em_breve) return "vencendo";
  return "pronta";
}

function SeloCertificado({
  grupo,
  certificado,
}: {
  grupo: string;
  certificado?: ResumoCertificado;
}) {
  if (grupo === "desconhecido")
    return (
      <span className="badge-neutral" title="Situação do certificado ainda não carregada">
        —
      </span>
    );
  if (grupo === "pronta")
    return (
      <span className="badge-ok" title={`Certificado válido até ${dataCurta(certificado?.validade)}`}>
        A1 até {dataCurta(certificado?.validade)}
      </span>
    );
  if (grupo === "vencendo")
    return (
      <span
        className="badge-warn"
        title={`Vence em ${dataCurta(certificado?.validade)} — renove com antecedência`}
      >
        vence em {certificado?.dias_para_vencer} d
      </span>
    );
  if (grupo === "vencido")
    return (
      <span className="badge-danger" title={`Venceu em ${dataCurta(certificado?.validade)}`}>
        A1 vencido
      </span>
    );
  return (
    <span className="badge-danger" title="Nenhum certificado A1 enviado para esta empresa">
      sem A1
    </span>
  );
}

export function SeletorEmpresas({
  empresas,
  certificados = null,
  selecionadas,
  aoMudar,
  estados,
  tipoAtivo,
}: {
  empresas: Empresa[];
  /**
   * Resumo de certificados por empresa — decide quem pode ser selecionada.
   * `null` (padrão) = ainda não carregado: ninguém é bloqueado por falta de dado.
   */
  certificados?: ResumoCertificado[] | null;
  selecionadas: Set<number>;
  aoMudar: (novo: Set<number>) => void;
  /** estado de sincronização por empresa+tipo, para o "em dia / na janela" */
  estados?: EstadoSincronizacao[];
  /** tipo escolhido no momento — a coluna de situação mostra este */
  tipoAtivo?: TipoDocumentoFiscal | "todos";
}) {
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<FiltroSeletor>("prontas");

  const certificadosCarregados = certificados != null;
  const certPorEmpresa = useMemo(() => {
    const mapa = new Map<number, ResumoCertificado>();
    for (const item of certificados ?? []) mapa.set(item.empresa_id, item);
    return mapa;
  }, [certificados]);

  const grupoPorEmpresa = useMemo(() => {
    const mapa = new Map<number, ReturnType<typeof grupoCertificado>>();
    for (const empresa of empresas)
      mapa.set(empresa.id, grupoCertificado(certPorEmpresa.get(empresa.id), certificadosCarregados));
    return mapa;
  }, [empresas, certPorEmpresa, certificadosCarregados]);

  const selecionavel = useCallback(
    (empresa: Empresa) => {
      const grupo = grupoPorEmpresa.get(empresa.id);
      return grupo === "pronta" || grupo === "vencendo" || grupo === "desconhecido";
    },
    [grupoPorEmpresa]
  );

  // Uma seleção salva pode ter virado obsoleta (certificado venceu, foi
  // removido). Enviar essas empresas de qualquer jeito só geraria erro na
  // prévia — limpar da seleção é mais honesto que descobrir depois. Só roda
  // quando o resumo de certificados de fato chegou.
  const podouRef = useRef(false);
  useEffect(() => {
    if (podouRef.current) return;
    if (empresas.length === 0 || !certificados || certificados.length === 0) return;
    podouRef.current = true;
    const invalidas = [...selecionadas].filter((id) => {
      const empresa = empresas.find((item) => item.id === id);
      return !empresa || !selecionavel(empresa);
    });
    if (invalidas.length > 0) {
      const proximo = new Set(selecionadas);
      for (const id of invalidas) proximo.delete(id);
      aoMudar(proximo);
    }
  }, [empresas, certificados, selecionadas, selecionavel, aoMudar]);

  const contagens = useMemo(() => {
    let prontas = 0;
    let vencidos = 0;
    let sem = 0;
    for (const grupo of grupoPorEmpresa.values()) {
      if (grupo === "pronta" || grupo === "vencendo") prontas += 1;
      else if (grupo === "vencido") vencidos += 1;
      else if (grupo === "sem") sem += 1;
    }
    return { prontas, vencidos, sem, todas: empresas.length };
  }, [grupoPorEmpresa, empresas]);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const digitos = termo.replace(/\D/g, "");
    let lista = empresas;
    if (filtro === "prontas")
      lista = lista.filter((e) =>
        ["pronta", "vencendo", ...(certificadosCarregados ? [] : ("desconhecido" as const))].includes(
          grupoPorEmpresa.get(e.id) ?? "sem"
        )
      );
    else if (filtro === "vencidos") lista = lista.filter((e) => grupoPorEmpresa.get(e.id) === "vencido");
    else if (filtro === "sem") lista = lista.filter((e) => grupoPorEmpresa.get(e.id) === "sem");
    if (termo) {
      lista = lista.filter(
        (e) =>
          e.razao_social.toLowerCase().includes(termo) ||
          (digitos.length > 0 && e.cnpj_cpf.includes(digitos)) ||
          e.uf.toLowerCase() === termo
      );
    }
    return [...lista].sort((a, b) => a.razao_social.localeCompare(b.razao_social, "pt-BR"));
  }, [empresas, grupoPorEmpresa, filtro, busca, certificadosCarregados]);

  const selecionaveisVisiveis = useMemo(() => visiveis.filter(selecionavel), [visiveis, selecionavel]);
  const todasMarcadas = selecionaveisVisiveis.length > 0 && selecionaveisVisiveis.every((e) => selecionadas.has(e.id));

  function alternar(id: number) {
    const proximo = new Set(selecionadas);
    if (proximo.has(id)) proximo.delete(id);
    else proximo.add(id);
    aoMudar(proximo);
  }

  function alternarTodasVisiveis() {
    const proximo = new Set(selecionadas);
    if (todasMarcadas) {
      for (const empresa of selecionaveisVisiveis) proximo.delete(empresa.id);
    } else {
      for (const empresa of selecionaveisVisiveis) proximo.add(empresa.id);
    }
    aoMudar(proximo);
  }

  function limparSelecao() {
    aoMudar(new Set());
  }

  function situacao(empresa: Empresa) {
    if (!estados) return null;

    const tipos: (TipoDocumentoFiscal | string)[] =
      tipoAtivo && tipoAtivo !== "todos" ? [tipoAtivo] : ["nfse", "nfe", "cte"];
    const linhas = estados.filter(
      (estado) => estado.empresa_id === empresa.id && tipos.includes(estado.tipo)
    );
    if (linhas.length === 0) return <span className="text-ink-muted">nunca consultada</span>;

    const travadas = linhas.filter((linha) => linha.travado || linha.em_andamento);
    if (travadas.length > 0) return <span className="text-warn">varrendo agora</span>;

    const bloqueadas = linhas.filter((linha) => linha.bloqueado_ate);
    if (bloqueadas.length > 0) {
      return (
        <span className="text-warn" title={bloqueadas[0].motivo_bloqueio ?? ""}>
          na janela da SEFAZ
        </span>
      );
    }

    const pendentes = linhas.filter((linha) => !linha.em_dia);
    if (pendentes.length === 0) return <span className="text-accent">em dia ✔</span>;
    if (pendentes.length === linhas.length) {
      return <span className="text-ink-muted">nunca consultada</span>;
    }
    return (
      <span className="text-ink-muted">
        {pendentes.length} de {linhas.length} com novidade
      </span>
    );
  }

  if (empresas.length === 0) {
    return (
      <div className="empty-state">
        <span className="inline-flex h-11 w-11 items-center justify-center rounded-[14px] bg-accent-soft text-accent-deep">
          <Icone nome="empresa" className="h-5 w-5" />
        </span>
        <p className="mt-4 font-display text-base font-extrabold text-ink">Nenhuma empresa cadastrada</p>
        <p className="mt-1 max-w-sm text-sm leading-6 text-ink-muted">
          Comece em <span className="font-semibold text-ink">Empresas → Importar em massa</span> para subir
          os certificados e cadastrar tudo de uma vez.
        </p>
        <div className="mt-5">
          <Link href="/dashboard/empresas" className="btn-primary btn-sm">
            Ir para Empresas
          </Link>
        </div>
      </div>
    );
  }

  const opcoesFiltro = [
    { id: "prontas", rotulo: "Prontas para importar", contador: contagens.prontas },
    { id: "vencidos", rotulo: "A1 vencido", contador: contagens.vencidos },
    { id: "sem", rotulo: "Sem certificado", contador: contagens.sem },
    { id: "todas", rotulo: "Todas", contador: contagens.todas },
  ];

  return (
    <section className="card overflow-hidden" aria-label="Seleção de empresas">
      {/* Barra de ferramentas: busca + filtros + ações de seleção. */}
      <div className="space-y-3 border-b border-line bg-surface-2/60 p-3 sm:p-4">
        <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center">
          <BuscaInput
            valor={busca}
            aoMudar={setBusca}
            placeholder="Buscar por razão social, CNPJ ou UF…"
            className="flex-1"
            ariaLabel="Buscar empresa na lista"
          />
          <div className="flex items-center gap-2 sm:flex-none">
            <button
              type="button"
              onClick={alternarTodasVisiveis}
              disabled={selecionaveisVisiveis.length === 0}
              className="btn-ghost btn-sm flex-1 sm:flex-none"
            >
              {todasMarcadas ? "Desmarcar visíveis" : "Marcar visíveis"}
            </button>
            {selecionadas.size > 0 && (
              <button type="button" onClick={limparSelecao} className="btn-ghost btn-sm flex-1 sm:flex-none">
                Limpar seleção
              </button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <ChipsFiltro
            opcoes={opcoesFiltro}
            valor={filtro}
            aoMudar={(valor) => setFiltro(valor as FiltroSeletor)}
            rotuloGrupo="Filtrar empresas por certificado"
          />
          <p className="text-xs text-ink-muted">
            {visiveis.length} de {empresas.length} na lista
            {selecionadas.size > 0 && (
              <>
                {" · "}
                <span className="font-bold text-accent-deep">{selecionadas.size} selecionada(s)</span>
              </>
            )}
          </p>
        </div>
      </div>

      {/* Cabeçalho das colunas (tabela em telas maiores). */}
      <div className="hidden grid-cols-[minmax(0,1fr)_2.75rem_9.5rem_10rem] items-center gap-3 border-b border-line bg-surface px-4 py-2 text-[10px] font-extrabold uppercase tracking-[.11em] text-ink-faint sm:grid">
        <p>Empresa</p>
        <p>UF</p>
        <p>Certificado</p>
        <p className="text-right">Situação</p>
      </div>

      <div className="max-h-[26rem] divide-y divide-line/75 overflow-y-auto">
        {visiveis.map((empresa) => {
          const grupo = grupoPorEmpresa.get(empresa.id) ?? "sem";
          const bloqueada = !selecionavel(empresa);
          const marcada = selecionadas.has(empresa.id);
          const certificado = certPorEmpresa.get(empresa.id);
          return (
            <label
              key={empresa.id}
              className={`grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 px-4 py-3 text-sm transition-colors sm:grid-cols-[auto_minmax(0,1fr)_2.75rem_9.5rem_10rem] ${
                marcada ? "bg-accent-soft/50" : "hover:bg-accent-soft/25"
              } ${bloqueada ? "cursor-not-allowed opacity-75" : ""}`}
              title={
                bloqueada
                  ? grupo === "vencido"
                    ? "Certificado vencido — renove para voltar a importar"
                    : "Sem certificado A1 — envie o certificado para habilitar"
                  : undefined
              }
            >
              <input
                type="checkbox"
                checked={marcada}
                disabled={bloqueada}
                onChange={() => alternar(empresa.id)}
                className="h-4 w-4 flex-none accent-accent"
                aria-label={`Selecionar ${empresa.razao_social}`}
              />
              <div className="min-w-0">
                <p className={`truncate font-semibold ${marcada ? "text-accent-deep" : "text-ink"}`}>
                  {empresa.razao_social}
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-ink-muted">
                  {formatarCnpjCpf(empresa.cnpj_cpf)}
                </p>
                {/* Em telas pequenas o certificado aparece junto do nome. */}
                <span className="mt-1.5 flex items-center gap-2 sm:hidden">
                  <SeloCertificado grupo={grupo} certificado={certificado} />
                  <span className="text-xs text-ink-muted">{situacao(empresa)}</span>
                </span>
              </div>
              <span className="hidden font-mono text-xs text-ink-muted sm:block">{empresa.uf}</span>
              <span className="hidden sm:block">
                <SeloCertificado grupo={grupo} certificado={certificado} />
              </span>
              <span className="hidden text-right text-xs sm:block">{situacao(empresa)}</span>
            </label>
          );
        })}

        {visiveis.length === 0 && (
          <div className="px-6 py-10 text-center">
            {filtro === "prontas" && !busca && contagens.prontas === 0 && certificados != null ? (
              <>
                <p className="font-display text-base font-extrabold text-ink">
                  Nenhuma empresa com certificado válido
                </p>
                <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-ink-muted">
                  A consulta na SEFAZ exige o certificado A1 de cada empresa. Envie os certificados e
                  elas aparecem aqui prontas para importar.
                </p>
                <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                  <Link href="/dashboard/certificados" className="btn-primary btn-sm">
                    Ver certificados
                  </Link>
                  <Link href="/dashboard/empresas" className="btn-ghost btn-sm">
                    Importar em massa
                  </Link>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm font-semibold text-ink">Nenhuma empresa bate com o filtro</p>
                <p className="mt-1 text-sm text-ink-muted">
                  Ajuste a busca ou escolha outro grupo de certificado.
                </p>
                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => {
                      setBusca("");
                      setFiltro("todas");
                    }}
                    className="btn-ghost btn-sm"
                  >
                    Limpar busca e filtro
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-surface-2/60 px-4 py-2.5">
        <p className="text-xs text-ink-muted">
          O pedido vai <span className="font-bold text-ink">somente para as marcadas</span> — cada
          consulta ocupa a janela de 1 h daquele CNPJ.
        </p>
        {contagens.vencidos + contagens.sem > 0 && (
          <Link href="/dashboard/certificados" className="link text-xs font-semibold">
            {contagens.vencidos + contagens.sem} empresa(s) precisam de certificado →
          </Link>
        )}
      </div>
    </section>
  );
}
