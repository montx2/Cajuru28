"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { PainelImportacao } from "@/components/PainelImportacao";
import type { Empresa, ResumoSincronizacao } from "@/lib/types";

/**
 * Visão geral — o começo do trabalho.
 *
 * A tela responde três perguntas na ordem em que elas aparecem para quem usa:
 * 1. o sistema está em dia? (contadores de sincronização)
 * 2. quais empresas eu quero importar agora? (painel de seleção)
 * 3. preciso fazer alguma coisa? (normalmente não — o agendador cuida)
 */
export default function VisaoGeralPage() {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [saude, setSaude] = useState<ResumoSincronizacao | null>(null);

  const carregar = useCallback(() => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
    api.resumoSincronizacao().then(setSaude).catch(() => {});
  }, []);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, 20_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  return (
    <div className="max-w-5xl">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-serif text-2xl text-ink">Visão geral</p>
          <p className="mt-1 text-sm text-ink-muted">
            {empresas.length} empresa{empresas.length === 1 ? "" : "s"} cadastrada
            {empresas.length === 1 ? "" : "s"}
            {saude && (
              <>
                {" · "}
                <span className="text-accent">{saude.em_dia} em dia</span>
                {saude.com_pendencia > 0 && (
                  <>
                    {" · "}
                    <span className="text-ink">{saude.com_pendencia} com documento novo</span>
                  </>
                )}
                {(saude.aguardando_janela > 0 || saude.bloqueadas_sefaz > 0) && (
                  <>
                    {" · "}
                    <span className="text-warn">
                      {saude.aguardando_janela + saude.bloqueadas_sefaz} na janela da SEFAZ
                    </span>
                  </>
                )}
                {" · "}
                <span>{saude.documentos_no_banco.toLocaleString("pt-BR")} documentos no banco</span>
              </>
            )}
          </p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link href="/dashboard/empresas" className="text-accent hover:underline">
            empresas
          </Link>
          <Link href="/dashboard/documentos" className="text-accent hover:underline">
            documentos
          </Link>
          <Link href="/dashboard/configuracoes" className="text-accent hover:underline">
            configurações
          </Link>
        </div>
      </div>

      <PainelImportacao aoDisparar={carregar} />

      {saude && (
        <section className="mt-8 border border-line bg-surface p-5 text-sm">
          <p className="mb-2 text-base font-medium text-ink">Como o sistema está trabalhando</p>
          {saude.sincronismo_automatico ? (
            <p className="text-ink-muted">
              O agendador consulta cada empresa sozinho a cada{" "}
              <span className="text-ink">{saude.intervalo_minutos} min</span>, respeitando a janela
              de 1 hora por empresa e tipo de documento que a SEFAZ exige. Nenhum clique é
              necessário — quem consultou fora da janela tem a continuação marcada e retomada
              automaticamente.
            </p>
          ) : (
            <p className="text-warn">
              Sincronismo automático desligado. As consultas só acontecem quando você dispara por
              aqui. Para ligar, abra{" "}
              <Link href="/dashboard/configuracoes" className="underline">
                Configurações
              </Link>
              .
            </p>
          )}
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs text-ink-muted">
            <span>
              <span className="font-mono text-ink">{saude.em_andamento}</span> varrendo agora
            </span>
            <span>
              <span className="font-mono text-ink">{saude.com_pendencia}</span> com documento novo
            </span>
            <span>
              <span className="font-mono text-ink">
                {saude.aguardando_janela + saude.bloqueadas_sefaz}
              </span>{" "}
              na janela da SEFAZ
            </span>
            <span>
              próxima rodada do agendador{" "}
              <span className="font-mono text-ink">
                {saude.tick_a_partir_de
                  ? new Date(saude.tick_a_partir_de).toLocaleTimeString("pt-BR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "—"}
              </span>
            </span>
          </div>
        </section>
      )}
    </div>
  );
}
