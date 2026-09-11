"use client";

import { useEffect, useMemo, useState } from "react";
import type { Empresa, EstadoSincronizacao, TipoDocumentoFiscal } from "@/lib/types";

/**
 * Lista de empresas com caixa de seleção — a peça que substitui o
 * "importar de todas".
 *
 * Por que isso existe: cada consulta à SEFAZ queima a janela de 1 hora *daquele
 * CNPJ*. Varrer 30 empresas quando o contador precisa de 3 não é só trabalho
 * jogado fora: atrasa justamente as 3 que importam, porque todas disputam as
 * mesmas horas do dia. Selecionar é a operação correta; "todas" virou apenas o
 * caso em que a pessoa marca todas.
 *
 * A seleção fica guardada no navegador: quem trabalha sempre com as mesmas 5
 * empresas não remarca a cada abertura do painel.
 */

const CHAVE_ARMAZENADA = "notasflow_empresas_selecionadas";

export function formatarDocumento(valor: string): string {
  const digitos = (valor || "").replace(/\D/g, "");
  if (digitos.length === 14) {
    return digitos.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
  }
  if (digitos.length === 11) {
    return digitos.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, "$1.$2.$3-$4");
  }
  return valor;
}

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

export function SeletorEmpresas({
  empresas,
  selecionadas,
  aoMudar,
  semCertificado,
  estados,
  tipoAtivo,
}: {
  empresas: Empresa[];
  selecionadas: Set<number>;
  aoMudar: (novo: Set<number>) => void;
  /** ids que não têm certificado ativo: aparecem, mas não são selecionáveis */
  semCertificado?: Set<number>;
  /** estado de sincronização por empresa+tipo, para o "em dia / na janela" */
  estados?: EstadoSincronizacao[];
  /** tipo escolhido no momento — a coluna de situação mostra este */
  tipoAtivo?: TipoDocumentoFiscal | "todos";
}) {
  const [busca, setBusca] = useState("");

  const filtradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const lista = termo
      ? empresas.filter(
          (empresa) =>
            empresa.razao_social.toLowerCase().includes(termo) ||
            empresa.cnpj_cpf.includes(termo.replace(/\D/g, ""))
        )
      : empresas;
    return [...lista].sort((a, b) => a.razao_social.localeCompare(b.razao_social));
  }, [empresas, busca]);

  const selecionaveis = filtradas.filter((empresa) => !semCertificado?.has(empresa.id));
  const todasMarcadas = selecionaveis.length > 0 && selecionaveis.every((e) => selecionadas.has(e.id));

  function alternar(id: number) {
    const proximo = new Set(selecionadas);
    if (proximo.has(id)) proximo.delete(id);
    else proximo.add(id);
    aoMudar(proximo);
  }

  function alternarTodasVisiveis() {
    const proximo = new Set(selecionadas);
    if (todasMarcadas) {
      for (const empresa of selecionaveis) proximo.delete(empresa.id);
    } else {
      for (const empresa of selecionaveis) proximo.add(empresa.id);
    }
    aoMudar(proximo);
  }

  function situacao(empresa: Empresa) {
    if (semCertificado?.has(empresa.id)) {
      return <span className="text-danger">sem certificado A1</span>;
    }
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
    return <span className="text-ink-muted">{pendentes.length} de {linhas.length} com novidade</span>;
  }

  if (empresas.length === 0) {
    return (
      <div className="border border-line bg-surface p-8 text-center">
        <p className="text-sm text-ink-muted">
          Nenhuma empresa cadastrada ainda. Comece em{" "}
          <span className="text-ink">Empresas → Importar em massa</span>.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={todasMarcadas}
            onChange={alternarTodasVisiveis}
            className="h-4 w-4 accent-accent"
          />
          {todasMarcadas ? "Desmarcar as visíveis" : "Selecionar as visíveis"}
        </label>
        <span className="text-xs text-ink-muted">
          {selecionadas.size} selecionada{selecionadas.size === 1 ? "" : "s"} de {empresas.length}
        </span>
        {empresas.length > 8 && (
          <input
            value={busca}
            onChange={(evento) => setBusca(evento.target.value)}
            placeholder="filtrar por nome ou CNPJ"
            className="ml-auto w-56 border border-line bg-bg px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
        )}
      </div>

      <div className="max-h-80 overflow-y-auto border border-line bg-bg">
        {filtradas.map((empresa) => {
          const bloqueada = semCertificado?.has(empresa.id) ?? false;
          const marcada = selecionadas.has(empresa.id);
          return (
            <label
              key={empresa.id}
              className={`flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2.5 text-sm last:border-0 hover:bg-surface ${
                marcada ? "bg-accent-soft/80" : ""
              } ${bloqueada ? "cursor-not-allowed opacity-60" : ""}`}
            >
              <input
                type="checkbox"
                checked={marcada}
                disabled={bloqueada}
                onChange={() => alternar(empresa.id)}
                className="h-4 w-4 accent-accent"
              />
              <span className="min-w-48 flex-1 text-ink">{empresa.razao_social}</span>
              <span className="font-mono text-xs text-ink-muted">
                {formatarDocumento(empresa.cnpj_cpf)}
              </span>
              <span className="w-8 text-xs text-ink-muted">{empresa.uf}</span>
              <span className="w-40 text-right text-xs">{situacao(empresa)}</span>
            </label>
          );
        })}
        {filtradas.length === 0 && (
          <p className="px-3 py-6 text-center text-sm text-ink-muted">
            Nenhuma empresa bate com o filtro.
          </p>
        )}
      </div>
    </div>
  );
}
