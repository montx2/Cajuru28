"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { PeriodoPicker } from "@/components/PeriodoPicker";
import { SeletorEmpresas, useSelecaoEmpresas } from "@/components/SeletorEmpresas";
import { horaLocal } from "@/lib/competencia";
import {
  erroDoPeriodo,
  paraFiltro,
  periodoPadrao,
  periodoValido,
  rotuloPeriodo,
  type Periodo,
} from "@/lib/periodo";
import {
  ROTULO_STATUS_SELECAO,
  ROTULO_TIPO,
  TIPOS,
  type Empresa,
  type EstadoSincronizacao,
  type ResultadoImportacaoSelecionada,
  type ResumoCertificado,
  type TipoDocumentoFiscal,
} from "@/lib/types";

/**
 * O painel de importação — usado na Visão geral e em Importações.
 *
 * Está em um componente (e não duplicado nas duas telas) por um motivo prático:
 * as regras que aparecem aqui — quem pode rodar agora, quem está na janela de
 * 1 hora da SEFAZ, quem está sem certificado — precisam ser **idênticas** nas
 * duas telas. Duas cópias significam uma tela dizendo "pode" e a outra "não".
 *
 * Todo o cálculo de "o que vai acontecer" vem do servidor (`/selecionadas/previa`):
 * a tela não tenta adivinhar janela de consumo, lease nem cooldown.
 */
export function PainelImportacao({
  aoDisparar,
  titulo = "Importar notas",
  periodoInicial,
  aoMudarPeriodo,
}: {
  /** Avisa a página para recarregar os contadores depois de um disparo. */
  aoDisparar?: () => void;
  titulo?: string;
  periodoInicial?: Periodo;
  aoMudarPeriodo?: (valor: Periodo) => void;
}) {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [tipo, setTipo] = useState<TipoDocumentoFiscal | "todos">("todos");
  const [periodo, setPeriodo] = useState<Periodo>(periodoInicial ?? periodoPadrao());
  const [estados, setEstados] = useState<EstadoSincronizacao[]>([]);
  // null = resumo ainda não chegou: o seletor não bloqueia ninguém por falta de dado.
  const [certificados, setCertificados] = useState<ResumoCertificado[] | null>(null);
  const [previa, setPrevia] = useState<ResultadoImportacaoSelecionada | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacaoSelecionada | null>(null);
  const [disparando, setDisparando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const { somenteLeitura } = usePapel();
  const { selecionadas, setSelecionadas } = useSelecaoEmpresas(empresas);

  const tiposDoPedido: TipoDocumentoFiscal[] = tipo === "todos" ? [...TIPOS] : [tipo];
  const idsSelecionados = useMemo(() => [...selecionadas].sort((a, b) => a - b), [selecionadas]);

  const carregar = useCallback(async () => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
    api.estadoSincronizacao().then(setEstados).catch(() => {});
    api.resumoCertificados().then(setCertificados).catch(() => {});
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const inicioExterno = periodoInicial?.inicio;
  const fimExterno = periodoInicial?.fim;
  useEffect(() => {
    if (inicioExterno && fimExterno) setPeriodo({ inicio: inicioExterno, fim: fimExterno });
  }, [inicioExterno, fimExterno]);

  function mudarPeriodo(valor: Periodo) {
    setPeriodo(valor);
    aoMudarPeriodo?.(valor);
  }

  const periodoOk = periodoValido(periodo);
  const avisoPeriodo = erroDoPeriodo(periodo);

  // Prévia automática, com atraso curto para não fazer uma chamada por clique.
  const tiposChave = tiposDoPedido.join(",");
  useEffect(() => {
    if (idsSelecionados.length === 0 || !periodoOk) {
      setPrevia(null);
      return;
    }
    let cancelado = false;
    const temporizador = setTimeout(async () => {
      try {
        const resposta = await api.previaImportacaoSelecionadas({
          empresa_ids: idsSelecionados,
          tipos: tiposChave.split(",") as TipoDocumentoFiscal[],
          ...paraFiltro(periodo),
        });
        if (!cancelado) setPrevia(resposta);
      } catch {
        if (!cancelado) setPrevia(null);
      }
    }, 350);
    return () => {
      cancelado = true;
      clearTimeout(temporizador);
    };
  }, [idsSelecionados, tiposChave, periodo.inicio, periodo.fim, periodoOk]);

  async function disparar(forcar = false) {
    if (idsSelecionados.length === 0 || !periodoOk) {
      // O período define o que será gravado; sem ele a importação despejaria
      // no acervo tudo o que a SEFAZ devolvesse por NSU.
      setErro(avisoPeriodo ?? "Marque ao menos uma empresa antes de importar.");
      return;
    }
    setDisparando(true);
    setErro(null);
    setResultado(null);
    try {
      const resposta = await api.importarSelecionadas({
        empresa_ids: idsSelecionados,
        tipos: tiposDoPedido,
        ...paraFiltro(periodo),
        forcar,
      });
      setResultado(resposta);
      await carregar();
      aoDisparar?.();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível disparar a importação agora.");
    } finally {
      setDisparando(false);
    }
  }

  const vencidos = (certificados ?? []).filter((item) => item.vencido);
  const vencendo = (certificados ?? []).filter((item) => item.vence_em_breve);

  const podemRodar = previa?.itens.filter((item) => item.status === "ok").length ?? 0;
  const naJanela = previa?.itens.filter((item) => item.status === "em_cooldown").length ?? 0;
  const semCert = previa?.itens.filter((item) => item.status === "sem_certificado").length ?? 0;

  return (
    <>
      {(vencidos.length > 0 || vencendo.length > 0) && (
        <div className="mb-6 border-l-2 border-danger bg-danger-soft px-4 py-3 text-sm">
          {vencidos.length > 0 && (
            <p className="text-danger">
              <strong>Certificado vencido:</strong>{" "}
              {vencidos.map((item) => item.razao_social).join(", ")}. Enquanto não for renovado, a
              importação dessas empresas não funciona.{" "}
              <Link href="/dashboard/empresas" className="underline">
                enviar certificado novo
              </Link>
            </p>
          )}
          {vencendo.length > 0 && (
            <p className={vencidos.length > 0 ? "mt-1 text-warn" : "text-warn"}>
              <strong>Certificado perto de vencer:</strong>{" "}
              {vencendo
                .map(
                  (item) =>
                    `${item.razao_social} (${item.dias_para_vencer} dia${
                      item.dias_para_vencer === 1 ? "" : "s"
                    })`
                )
                .join(", ")}
              . Renove com antecedência — o A1 leva alguns dias para sair.
            </p>
          )}
        </div>
      )}

      <section className="card-pad">
        <p className="mb-1 text-base font-semibold text-ink">{titulo}</p>
        <p className="mb-5 text-sm text-ink-muted">
          Escolha o período, marque as empresas e clique em importar. A lista mostra por padrão
          apenas as empresas com certificado válido — a pré-condição da consulta na SEFAZ. A
          varredura na origem continua sendo por NSU — é o único jeito que ela aceita —, mas só
          entram no acervo as notas emitidas dentro do período pedido.
        </p>

        <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-4">
          <div>
            <p className="label">
              Período <span className="text-danger">*</span>
            </p>
            <PeriodoPicker valor={periodo} aoMudar={mudarPeriodo} idPrefixo="importacao" />
            {avisoPeriodo && <p className="mt-1 text-xs text-danger">{avisoPeriodo}</p>}
          </div>
          <div>
            <p className="label">O que puxar</p>
            <select
              value={tipo}
              onChange={(e) => setTipo(e.target.value as TipoDocumentoFiscal | "todos")}
              className="input"
            >
              <option value="todos">NFS-e + NFe + CT-e</option>
              {TIPOS.map((item) => (
                <option key={item} value={item}>
                  {ROTULO_TIPO[item]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <SeletorEmpresas
          empresas={empresas}
          certificados={certificados}
          selecionadas={selecionadas}
          aoMudar={setSelecionadas}
          estados={estados}
          tipoAtivo={tipo}
        />

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3">
          <button
            type="button"
            onClick={() => disparar(false)}
            disabled={disparando || idsSelecionados.length === 0 || !periodoOk || somenteLeitura}
            title={
              somenteLeitura
                ? "Seu perfil é somente leitura."
                : (avisoPeriodo ?? undefined)
            }
            className="btn-primary"
          >
            {disparando
              ? "Disparando…"
              : `Importar ${selecionadas.size} empresa${selecionadas.size === 1 ? "" : "s"} · ${rotuloPeriodo(periodo)}`}
          </button>
          {somenteLeitura && <p className="badge-neutral">perfil somente leitura</p>}

          {previa && (
            <p className="text-sm text-ink-muted">
              {podemRodar > 0 && <span className="text-accent">{podemRodar} pronto(s)</span>}
              {naJanela > 0 && (
                <>
                  {podemRodar > 0 && " · "}
                  <span className="text-warn">{naJanela} aguardando janela</span>
                </>
              )}
              {semCert > 0 && (
                <>
                  {(podemRodar > 0 || naJanela > 0) && " · "}
                  <span className="text-danger">{semCert} sem certificado</span>
                </>
              )}
            </p>
          )}
        </div>

        <details className="mt-3 text-xs text-ink-muted">
          <summary className="cursor-pointer text-ink-muted hover:text-ink">opções avançadas</summary>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => disparar(true)}
              disabled={disparando || idsSelecionados.length === 0 || !periodoOk || somenteLeitura}
              title="Atravessa a janela de 1 hora. Use só quando tiver certeza."
              className="btn-ghost btn-sm"
            >
              Forçar janela
            </button>
            <span>
              A varredura na origem continua sendo por NSU (a SEFAZ não aceita recorte por data),
              então tudo o que estiver na fila é baixado — mas o que estiver fora do período é
              descartado antes de entrar no acervo, e a execução informa quantas notas foram.
            </span>
          </div>
        </details>

        {erro && (
          <p className="mt-4 border border-danger-soft bg-danger-soft px-3 py-2 text-sm text-danger">
            {erro}
          </p>
        )}

        {resultado && <TabelaResultado resultado={resultado} />}
      </section>
    </>
  );
}

function TabelaResultado({ resultado }: { resultado: ResultadoImportacaoSelecionada }) {
  return (
    <div className="mt-5 rounded-xl border border-line bg-surface-2/80 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm text-ink">
        {resultado.enfileiradas > 0 ? (
          <span className="badge-ok">{resultado.enfileiradas} enfileirada(s)</span>
        ) : (
          <span className="badge-warn">Nada enfileirado</span>
        )}
        {resultado.aguardando > 0 && <span className="badge-warn">{resultado.aguardando} aguardando</span>}
        {resultado.ignoradas > 0 && <span className="badge-neutral">{resultado.ignoradas} ignorada(s)</span>}
        <Link href="/dashboard/importacoes" className="link ml-auto text-xs font-semibold">
          acompanhar →
        </Link>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-ink-muted hover:text-ink">ver detalhes por empresa</summary>
        <div className="mt-2 max-h-72 overflow-y-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-ink-muted">
              <th className="py-2 font-normal">Empresa</th>
              <th className="py-2 font-normal">Tipo</th>
              <th className="py-2 font-normal">Situação</th>
            </tr>
          </thead>
          <tbody>
            {resultado.itens.map((item) => (
              <tr
                key={`${item.empresa_id}-${item.tipo}`}
                className="border-b border-line last:border-0"
              >
                <td className="py-2 text-ink">{item.razao_social}</td>
                <td className="py-2 text-ink-muted">{ROTULO_TIPO[item.tipo]}</td>
                <td className="py-2">
                  <span
                    className={
                      item.enfileirada
                        ? "text-accent"
                        : item.status === "em_cooldown"
                          ? "text-warn"
                          : "text-ink-muted"
                    }
                  >
                    {ROTULO_STATUS_SELECAO[item.status] ?? item.status}
                  </span>
                  {item.disponivel_em && (
                    <span className="ml-1 text-xs text-warn">
                      retoma {horaLocal(item.disponivel_em)}
                    </span>
                  )}
                  {item.mensagem && (
                    <span className="ml-1 text-xs text-ink-muted" title={item.mensagem}>
                      — {item.mensagem.slice(0, 110)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </details>
    </div>
  );
}
