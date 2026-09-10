"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { EstadoAtualizacao } from "@/lib/types";
import { bytesParaTexto } from "@/lib/competencia";

/**
 * Faixa de aviso de atualização, no topo do painel.
 *
 * A regra que ela segue: **nunca interromper o trabalho**. Uma versão nova é
 * informação, não um modal — o contador pode estar no meio de um fechamento, e
 * um programa que sequestra a tela para pedir reinício é um programa que
 * atrapalha. A faixa informa, mostra o tamanho do download e deixa a decisão
 * nas mãos de quem está usando.
 *
 * Só quando a instalação começa é que ela vira o elemento principal da tela —
 * porque aí o programa realmente vai fechar.
 */
export function AvisoAtualizacao() {
  const [estado, setEstado] = useState<EstadoAtualizacao | null>(null);
  const [aplicando, setAplicando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [dispensado, setDispensado] = useState<string | null>(null);

  const consultar = useCallback(async () => {
    try {
      setEstado(await api.estadoAtualizacao());
    } catch {
      /* sem sessão ou fora do ar: silêncio é melhor que um erro a cada 30s */
    }
  }, []);

  useEffect(() => {
    consultar();
    const intervalo = setInterval(consultar, 30_000);
    return () => clearInterval(intervalo);
  }, [consultar]);

  // Enquanto baixa/instala, acompanha de perto — o programa vai fechar.
  useEffect(() => {
    if (!estado || !["baixando", "verificando_hash", "instalando"].includes(estado.etapa)) return;
    const intervalo = setInterval(consultar, 1_500);
    return () => clearInterval(intervalo);
  }, [estado, consultar]);

  async function aplicar() {
    setAplicando(true);
    setErro(null);
    try {
      await api.aplicarAtualizacao();
      await consultar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível iniciar a atualização.");
    } finally {
      setAplicando(false);
    }
  }

  if (!estado) return null;

  const baixando = ["baixando", "verificando_hash"].includes(estado.etapa);
  const instalando = estado.etapa === "instalando";
  const disponivel = estado.disponivel;

  if (instalando) {
    return (
      <div className="border-b border-line bg-accent-soft px-8 py-3 text-sm text-ink">
        <p className="font-medium">
          Atualizando para a versão {disponivel?.versao} — o NotasFlow vai fechar e reabrir sozinho.
        </p>
        <p className="text-ink-muted">
          Pode deixar aberto: nada do que está no banco ou nos certificados é perdido.
        </p>
      </div>
    );
  }

  if (baixando) {
    const porcentagem =
      estado.total > 0 ? Math.min(100, Math.round((estado.baixado / estado.total) * 100)) : null;
    return (
      <div className="border-b border-line bg-accent-soft px-8 py-3 text-sm text-ink">
        <p className="font-medium">
          {estado.etapa === "verificando_hash"
            ? "Conferindo o arquivo baixado…"
            : `Baixando a versão ${disponivel?.versao ?? "nova"}…`}
        </p>
        {porcentagem !== null && (
          <div className="mt-2 h-1.5 w-full max-w-md bg-line">
            <div className="h-full bg-accent transition-all" style={{ width: `${porcentagem}%` }} />
          </div>
        )}
      </div>
    );
  }

  if (estado.etapa === "erro" && estado.erro) {
    return (
      <div className="border-b border-line bg-danger-soft px-8 py-3 text-sm text-danger">
        <p>
          <strong>A atualização falhou.</strong> {estado.erro}
        </p>
        <button type="button" onClick={aplicar} className="mt-1 underline">
          tentar de novo
        </button>
      </div>
    );
  }

  if (!disponivel || dispensado === disponivel.versao) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-accent-soft px-8 py-3 text-sm">
      <p className="text-ink">
        <strong>Versão {disponivel.versao} disponível.</strong>{" "}
        <span className="text-ink-muted">
          você tem a {estado.versao_atual}
          {disponivel.tamanho ? ` · download de ${bytesParaTexto(disponivel.tamanho)}` : ""}
        </span>
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={aplicar}
          disabled={aplicando}
          className="bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {aplicando ? "Iniciando…" : "Atualizar agora"}
        </button>
        {!disponivel.obrigatoria && (
          <button
            type="button"
            onClick={() => setDispensado(disponivel.versao)}
            className="text-xs text-ink-muted hover:text-ink"
          >
            depois
          </button>
        )}
        <Link href="/dashboard/configuracoes" className="text-xs text-accent hover:underline">
          detalhes
        </Link>
      </div>
      {erro && <p className="w-full text-xs text-danger">{erro}</p>}
      {disponivel.notas && (
        <p className="w-full text-xs text-ink-muted">{disponivel.notas.split("\n")[0]}</p>
      )}
    </div>
  );
}
