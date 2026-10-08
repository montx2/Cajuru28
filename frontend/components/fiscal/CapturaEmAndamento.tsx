"use client";

import { useEffect, useState } from "react";
import { Botao } from "@/components/ui/Botao";
import { Aviso } from "@/components/ui/Aviso";
import { BotaoLink } from "@/components/ui/Botao";
import { contagem, numero, tempoRelativo } from "@/lib/format";
import { ROTULO_TIPO, type CapturaAoVivo, type ExecucaoAoVivo, type TipoDocumentoFiscal } from "@/lib/types";

/** Quanto tempo o desfecho de uma captura continua sendo notícia na lista. */
export const JANELA_DESFECHO_MS = 5 * 60 * 1000;

export interface CapturaEmAndamentoProps {
  captura: CapturaAoVivo | null;
  /** Recarrega lista e resumo agora (o mesmo caminho do polling). */
  aoAtualizar: () => void;
  /** Nome da empresa do filtro, quando há uma — o texto fala do recorte. */
  escopo?: string | null;
  className?: string;
}

function rotuloDoTipo(tipo: string): string {
  return ROTULO_TIPO[tipo as TipoDocumentoFiscal] ?? tipo.toUpperCase();
}

/** "NFe · Alfa Ltda" para uma; "3 empresas" para várias. */
function resumoDasRodadas(rodadas: ExecucaoAoVivo[]): string {
  if (rodadas.length === 1) {
    const unica = rodadas[0];
    return `${rotuloDoTipo(unica.tipo)} · ${unica.razao_social}`;
  }
  const empresas = new Set(rodadas.map((rodada) => rodada.empresa_id)).size;
  return `${contagem(empresas, "empresa", "empresas")} · ${contagem(rodadas.length, "frente de captura", "frentes de captura")}`;
}

/**
 * Aviso de captura na lista do acervo.
 *
 * A importação demora — é uma consulta por NSU na SEFAZ —, e a lista mostra o
 * que **já** chegou, não o que está chegando. Sem dizer isso, o operador olha
 * uma lista parada e conclui que o sistema pegou tudo, ou que não veio nada.
 *
 * Três estados, na ordem em que importam para quem está olhando:
 *
 * 1. **capturando** (tom de espera, com a contagem viva): a lista está
 *    incompleta e se completa sozinha. Se alguma rodada está esperando a janela
 *    da SEFAZ, diz isso e quando volta — senão "nada chegando" parece travado;
 * 2. **captura em outras empresas** (informativo): o recorte está parado, mas o
 *    escritório está trabalhando;
 * 3. **desfecho recente**: terminou — com N documentos novos, sem documento
 *    novo, ou com erro. É a resposta explícita para "não veio nenhum", e some
 *    sozinho depois de `JANELA_DESFECHO_MS` (ou no clique de fechar).
 */
export function CapturaEmAndamento({ captura, aoAtualizar, escopo, className }: CapturaEmAndamentoProps) {
  const [desfechoFechado, setDesfechoFechado] = useState<number | null>(null);

  const emAndamento = captura?.em_andamento ?? [];
  const ultima = captura?.ultima ?? null;
  const idUltima = ultima?.id ?? null;

  // Nova captura terminou? O fechamento anterior não vale mais para ela.
  useEffect(() => {
    if (idUltima !== null && desfechoFechado !== null && idUltima !== desfechoFechado) {
      setDesfechoFechado(null);
    }
  }, [idUltima, desfechoFechado]);

  if (emAndamento.length > 0) {
    const total = captura?.documentos_em_andamento ?? 0;
    const aguardando = emAndamento.filter((rodada) => rodada.status === "aguardando");
    const trabalhando = emAndamento.length - aguardando.length;
    const recorte = escopo ? `em ${escopo}` : "no escritório";

    return (
      <Aviso
        data-captura="em-andamento"
        tom="espera"
        icone="sincronizar"
        titulo={trabalhando > 0 ? "Capturando documentos…" : "Captura aguardando a SEFAZ"}
        className={className}
        acao={
          <>
            <Botao variante="secundaria" tamanho="sm" onClick={aoAtualizar}>
              Atualizar agora
            </Botao>
            <BotaoLink variante="link" tamanho="sm" href="/dashboard/execucoes?aba=fila">
              Acompanhar na central
            </BotaoLink>
          </>
        }
      >
        <p>
          {/* A contagem é da rodada, não da lista: é o que responde "está vindo algo?". */}
          {total > 0
            ? `${contagem(total, "documento já entrou", "documentos já entraram")} nesta captura`
            : "Nenhum documento novo ainda nesta captura"}
          {" · "}
          {resumoDasRodadas(emAndamento)} {recorte}.
        </p>
        <p className="mt-1">
          Esta lista está incompleta de propósito: ela se atualiza sozinha a cada poucos segundos, até a captura
          terminar.
        </p>
        {aguardando.length > 0 ? (
          <p className="mt-1">
            {contagem(aguardando.length, "rodada está", "rodadas estão")} na janela de consumo da SEFAZ
            {trabalhando > 0 ? " e seguem depois dela" : ""}
            {aguardando[0].aguardando_ate
              ? ` — volta ${tempoRelativo(aguardando[0].aguardando_ate)}`
              : ""}
            .
          </p>
        ) : null}
      </Aviso>
    );
  }

  if ((captura?.fora_do_recorte ?? 0) > 0) {
    return (
      <Aviso
        data-captura="fora-do-recorte"
        tom="info"
        icone="info"
        className={className}
        acao={
          <BotaoLink variante="link" tamanho="sm" href="/dashboard/execucoes?aba=fila">
            Ver o que está rodando
          </BotaoLink>
        }
      >
        {contagem(captura?.fora_do_recorte ?? 0, "captura está rodando", "capturas estão rodando")} em outras
        empresas. Este recorte não muda por causa delas.
      </Aviso>
    );
  }

  if (ultima === null || ultima.id === desfechoFechado) return null;
  const quando = ultima.finalizado_em ? new Date(ultima.finalizado_em).getTime() : 0;
  const recente = Number.isFinite(quando) && Date.now() - quando <= JANELA_DESFECHO_MS;
  if (!recente) return null;

  const onde = ultima.empresa_razao_social ?? "a empresa";
  const fechar = () => setDesfechoFechado(ultima.id);

  if (ultima.status === "erro") {
    return (
      <Aviso
        data-captura="falhou"
        tom="erro"
        icone="alerta"
        titulo="A captura terminou com erro"
        className={className}
        aoFechar={fechar}
        acao={
          <BotaoLink variante="link" tamanho="sm" href="/dashboard/execucoes">
            Ver o que aconteceu
          </BotaoLink>
        }
      >
        {ultima.mensagem_erro ?? `A rodada de ${onde} não terminou.`} Nada foi perdido: a captura continua do
        ponto em que parou.
      </Aviso>
    );
  }

  const novos = ultima.documentos_importados ?? 0;
  if (novos === 0) {
    return (
      <Aviso data-captura="sem-novidade" tom="neutro" icone="verificar-circulo" className={className} aoFechar={fechar}>
        <span className="font-medium text-tinta-forte">A captura terminou e não trouxe documento novo</span> para{" "}
        {onde}. A fonte não tinha nada além do que já está nesta lista
        {ultima.documentos_no_periodo === 0 && (ultima.documentos_fora_do_periodo ?? 0) > 0
          ? ` (${numero(ultima.documentos_fora_do_periodo ?? 0)} documento(s) chegaram fora do período e ficaram guardados no acervo)`
          : ""}
        .
      </Aviso>
    );
  }

  return (
    <Aviso
      data-captura="concluida"
      tom="ok"
      icone="verificar-circulo"
      titulo="Captura concluída"
      className={className}
      aoFechar={fechar}
      acao={
        <Botao variante="secundaria" tamanho="sm" onClick={aoAtualizar}>
          Atualizar agora
        </Botao>
      }
    >
      {contagem(novos, "documento novo entrou", "documentos novos entraram")} em {onde}.
      {ultima.documentos_fora_do_periodo && ultima.documentos_fora_do_periodo > 0
        ? ` Outros ${numero(ultima.documentos_fora_do_periodo)} ficaram fora do período pedido — estão no acervo, não neste recorte.`
        : ""}
    </Aviso>
  );
}
