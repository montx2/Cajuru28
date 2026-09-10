"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { CompetenciaPicker } from "@/components/CompetenciaPicker";
import { SeletorEmpresas, useSelecaoEmpresas } from "@/components/SeletorEmpresas";
import { horaLocal, paraAPI } from "@/lib/competencia";
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
}: {
  /** Avisa a página para recarregar os contadores depois de um disparo. */
  aoDisparar?: () => void;
  titulo?: string;
}) {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [tipo, setTipo] = useState<TipoDocumentoFiscal | "todos">("todos");
  const [competencia, setCompetencia] = useState<string | null>(null);
  const [estados, setEstados] = useState<EstadoSincronizacao[]>([]);
  const [certificados, setCertificados] = useState<ResumoCertificado[]>([]);
  const [previa, setPrevia] = useState<ResultadoImportacaoSelecionada | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacaoSelecionada | null>(null);
  const [disparando, setDisparando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
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

  // Prévia automática, com atraso curto para não fazer uma chamada por clique.
  const tiposChave = tiposDoPedido.join(",");
  useEffect(() => {
    if (idsSelecionados.length === 0) {
      setPrevia(null);
      return;
    }
    let cancelado = false;
    const temporizador = setTimeout(async () => {
      try {
        const resposta = await api.previaImportacaoSelecionadas({
          empresa_ids: idsSelecionados,
          tipos: tiposChave.split(",") as TipoDocumentoFiscal[],
          competencia: paraAPI(competencia),
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
  }, [idsSelecionados, tiposChave, competencia]);

  async function disparar(forcar = false) {
    if (idsSelecionados.length === 0) return;
    setDisparando(true);
    setErro(null);
    setResultado(null);
    try {
      const resposta = await api.importarSelecionadas({
        empresa_ids: idsSelecionados,
        tipos: tiposDoPedido,
        competencia: paraAPI(competencia),
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

  const semCertificado = useMemo(
    () =>
      new Set(
        certificados.filter((item) => !item.tem_certificado).map((item) => item.empresa_id)
      ),
    [certificados]
  );
  const vencidos = certificados.filter((item) => item.vencido);
  const vencendo = certificados.filter((item) => item.vence_em_breve);

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

      <section className="border border-line bg-surface p-6">
        <p className="mb-1 text-base font-medium text-ink">{titulo}</p>
        <p className="mb-5 text-sm text-ink-muted">
          Marque as empresas que você quer e clique em importar. Cada consulta gasta a janela de
          1 hora <em>daquele CNPJ</em> na SEFAZ — importar só o que foi pedido deixa a fila mais
          rápida para todo mundo.
        </p>

        <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-4">
          <div>
            <p className="mb-2 text-xs uppercase text-ink-muted">Competência</p>
            <CompetenciaPicker valor={competencia} aoMudar={setCompetencia} />
          </div>
          <div>
            <p className="mb-2 text-xs uppercase text-ink-muted">O que puxar</p>
            <select
              value={tipo}
              onChange={(e) => setTipo(e.target.value as TipoDocumentoFiscal | "todos")}
              className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
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
          selecionadas={selecionadas}
          aoMudar={setSelecionadas}
          semCertificado={semCertificado}
          estados={estados}
          tipoAtivo={tipo}
        />

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3">
          <button
            type="button"
            onClick={() => disparar(false)}
            disabled={disparando || idsSelecionados.length === 0}
            className="bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {disparando
              ? "Disparando…"
              : `Importar ${selecionadas.size} empresa${selecionadas.size === 1 ? "" : "s"}`}
          </button>
          <button
            type="button"
            onClick={() => disparar(true)}
            disabled={disparando || idsSelecionados.length === 0}
            title="Atravessa a janela de 1 hora da SEFAZ. Só com certeza: insistir antes da hora zera o cronômetro do bloqueio."
            className="border border-line px-3 py-2 text-sm text-ink-muted hover:border-accent hover:text-ink disabled:opacity-40"
          >
            Forçar janela
          </button>

          {previa && (
            <p className="text-sm text-ink-muted">
              {podemRodar > 0 && (
                <span className="text-accent">{podemRodar} pode(m) rodar agora</span>
              )}
              {naJanela > 0 && (
                <>
                  {podemRodar > 0 && " · "}
                  <span className="text-warn">{naJanela} na janela de 1 h</span>
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

        <p className="mt-3 max-w-2xl text-xs text-ink-muted">
          A competência <span className="text-ink">não</span> limita o que é baixado — a SEFAZ só
          anda por NSU, então baixar tudo é o que garante que nenhuma nota se perca. O mês escolhe
          o que é contado na tela e o que entra no ZIP.
        </p>

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
    <div className="mt-5 border-t border-line pt-4">
      <p className="mb-2 text-sm text-ink">
        {resultado.enfileiradas > 0 ? (
          <>
            <span className="text-accent">
              {resultado.enfileiradas} varredura(s) enfileirada(s)
            </span>
            {resultado.aguardando > 0 && (
              <>
                {" · "}
                <span className="text-warn">{resultado.aguardando} na janela da SEFAZ</span>
              </>
            )}
            {resultado.ignoradas > 0 && <> · {resultado.ignoradas} ignorada(s)</>}
          </>
        ) : (
          <span className="text-warn">Nada foi enfileirado — veja o motivo de cada linha.</span>
        )}{" "}
        <Link href="/dashboard/importacoes" className="text-accent hover:underline">
          acompanhar
        </Link>
      </p>
      <div className="max-h-72 overflow-y-auto">
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
    </div>
  );
}
