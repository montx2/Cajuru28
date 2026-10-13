"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { contagem, numero } from "@/lib/format";
import { mensagemDoErro } from "@/lib/erros";
import type { ResultadoManifestacaoConclusiva, TipoManifestacaoConclusiva } from "@/lib/types";
import { Area, Aviso, Botao, DialogoConfirmacao, GrupoRadio } from "@/components/ui";
import type { TamanhoBotao, VarianteBotao } from "@/components/ui/Botao";
import { useToast } from "@/components/ui/Toast";

const TIPOS: { valor: TipoManifestacaoConclusiva; rotulo: string; ajuda: string }[] = [
  {
    valor: "confirmacao",
    rotulo: "Confirmação da Operação",
    ajuda:
      "As operações ocorreram e as mercadorias foram recebidas. É a escolha quando as notas são legítimas. Impede o emitente de cancelar as NF-es depois.",
  },
  {
    valor: "desconhecimento",
    rotulo: "Desconhecimento da Operação",
    ajuda:
      "A empresa não reconhece as operações. Atenção: por regra da SEFAZ este evento NÃO devolve o XML completo.",
  },
  {
    valor: "nao_realizada",
    rotulo: "Operação não Realizada",
    ajuda:
      "As operações não aconteceram (recusa de mercadoria, devolução, emissão em duplicidade). Exige justificativa.",
  },
];

/**
 * Manifestação conclusiva de VÁRIAS NF-es presas em resumo de uma vez.
 *
 * É o caminho das notas que passaram dos 10 dias da Ciência (cStat 596): a via
 * automática não é mais aceita e cada nota precisa de um evento conclusivo
 * para liberar o XML. Como é ato de negócio, o operador escolhe o tipo e
 * confirma — mas escolhe uma vez para o lote, não nota por nota.
 */
export function ManifestacaoConclusivaLote({
  ids,
  aoConcluir,
  variante = "primaria",
  tamanho = "sm",
  rotulo,
  desabilitado = false,
  motivo,
}: {
  /** Ids das NF-es (no máximo 100 por vez — limite da API). */
  ids: number[];
  aoConcluir: () => void;
  variante?: VarianteBotao;
  tamanho?: TamanhoBotao;
  rotulo?: string;
  desabilitado?: boolean;
  motivo?: string;
}) {
  const { avisar } = useToast();
  const [aberto, setAberto] = useState(false);
  const [tipo, setTipo] = useState<TipoManifestacaoConclusiva>("confirmacao");
  const [justificativa, setJustificativa] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultados, setResultados] = useState<ResultadoManifestacaoConclusiva[] | null>(null);

  const escolhido = TIPOS.find((item) => item.valor === tipo) ?? TIPOS[0];
  const exigeJustificativa = tipo !== "confirmacao";
  const justificativaCurta = exigeJustificativa && justificativa.trim().length < 15;
  const lote = ids.slice(0, 100);

  function fechar() {
    setAberto(false);
    setErro(null);
    setResultados(null);
    setJustificativa("");
  }

  async function enviar() {
    if (exigeJustificativa && justificativaCurta) {
      setErro("A SEFAZ exige justificativa de 15 a 255 caracteres para este evento.");
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await api.manifestarConclusiva(lote, tipo, justificativa.trim());
      setResultados(resposta);
      const ok = resposta.filter((item) => item.ok).length;
      const recusadas = resposta.length - ok;
      avisar({
        tom: recusadas === 0 ? "ok" : "espera",
        titulo: `${contagem(ok, "manifestação registrada", "manifestações registradas")}`,
        descricao:
          recusadas > 0
            ? `${contagem(recusadas, "nota recusada", "notas recusadas")} pela SEFAZ — veja o motivo na lista.`
            : "A SEFAZ vai liberar os XMLs completos. A busca roda sozinha nos próximos minutos.",
      });
      aoConcluir();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "registrar as manifestações"));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <Botao
        tamanho={tamanho}
        variante={variante}
        onClick={() => setAberto(true)}
        disabled={desabilitado || lote.length === 0}
        title={desabilitado ? motivo : lote.length === 0 ? "Nenhuma nota pendente" : undefined}
      >
        {rotulo ?? `Manifestar ${contagem(lote.length, "nota", "notas")}`}
      </Botao>

      <DialogoConfirmacao
        aberto={aberto}
        aoFechar={fechar}
        aoConfirmar={resultados ? fechar : enviar}
        titulo="Manifestação conclusiva em lote"
        consequencia={
          <>
            {contagem(lote.length, "evento será enviado", "eventos serão enviados")} ao Ambiente Nacional{" "}
            <strong>em nome da empresa</strong> com o certificado A1. É irreversível e encerra a manifestação
            destas NF-es.
          </>
        }
        impacto={
          resultados ? (
            <div className="space-y-1 text-left">
              {resultados.map((item) => (
                <p key={item.documento_id} className="text-xs leading-5">
                  <span className={item.ok ? "font-medium text-ok" : "font-medium text-erro"}>
                    {item.ok ? "Registrada" : "Recusada"}
                  </span>{" "}
                  <span className="text-tinta-suave">
                    · nota #{numero(item.documento_id)} — {item.mensagem}
                  </span>
                </p>
              ))}
            </div>
          ) : (
            <div className="space-y-3 text-left">
              <p className="text-sm text-tinta-suave">
                Estas notas passaram dos 10 dias da Ciência da Operação (recusa 596 da SEFAZ). Só um evento
                conclusivo libera o XML completo de cada uma.
              </p>
              <GrupoRadio
                rotulo="O que aconteceu com as operações?"
                name="tipo-manifestacao-lote"
                horizontal={false}
                valor={tipo}
                aoMudar={(valor) => setTipo(valor as TipoManifestacaoConclusiva)}
                opcoes={TIPOS.map((item) => ({ valor: item.valor, rotulo: item.rotulo }))}
              />
              <p className="text-xs leading-5 text-tinta-suave">{escolhido.ajuda}</p>
              {exigeJustificativa ? (
                <Area
                  rotulo="Justificativa"
                  descricao="Vai no XML de cada evento (xJust). A SEFAZ exige de 15 a 255 caracteres."
                  value={justificativa}
                  onChange={(evento) => setJustificativa(evento.target.value)}
                  rows={3}
                  maxLength={255}
                  erro={justificativa && justificativaCurta ? "Escreva ao menos 15 caracteres." : undefined}
                />
              ) : null}
              {erro ? (
                <Aviso tom="erro" compacto urgente>
                  {erro}
                </Aviso>
              ) : null}
            </div>
          )
        }
        rotuloConfirmar={resultados ? "Concluir" : "Registrar na SEFAZ"}
        carregando={enviando}
        largura="larga"
      />
    </>
  );
}
