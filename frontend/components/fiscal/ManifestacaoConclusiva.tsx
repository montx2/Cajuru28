"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { chaveEmGrupos } from "@/lib/format";
import type { DocumentoDetalhe, TipoManifestacaoConclusiva } from "@/lib/types";
import { Area, Botao, DialogoConfirmacao, GrupoRadio, Icone } from "@/components/ui";
import { useToast } from "@/components/ui/Toast";

const TIPOS: { valor: TipoManifestacaoConclusiva; rotulo: string; ajuda: string }[] = [
  {
    valor: "confirmacao",
    rotulo: "Confirmação da Operação",
    ajuda:
      "A operação ocorreu e a mercadoria foi recebida. É a escolha quando a nota é legítima. Impede o emitente de cancelar a NF-e depois.",
  },
  {
    valor: "desconhecimento",
    rotulo: "Desconhecimento da Operação",
    ajuda:
      "A empresa não reconhece a operação. Atenção: por regra da SEFAZ este evento NÃO devolve o XML completo.",
  },
  {
    valor: "nao_realizada",
    rotulo: "Operação não Realizada",
    ajuda:
      "A operação não aconteceu (recusa de mercadoria, devolução, emissão em duplicidade). Exige justificativa.",
  },
];

/**
 * Manifestação conclusiva de uma NF-e presa em resumo.
 *
 * Existe porque a **Ciência da Operação** — a via automática — só é aceita até
 * 10 dias da autorização: passado o prazo a SEFAZ responde `cStat 596` e a nota
 * nunca mais sai do `resNFe` sozinha. Os eventos conclusivos (Confirmação,
 * Desconhecimento, Operação não Realizada) destravam o XML completo, mas dizem
 * à SEFAZ o que aconteceu com a operação — então quem decide é o operador, não
 * o robô. O diálogo diz o efeito de cada escolha antes do clique.
 */
export function ManifestacaoConclusiva({
  documento,
  aoConcluir,
}: {
  documento: DocumentoDetalhe;
  aoConcluir: () => void;
}) {
  const { avisar } = useToast();
  const [aberto, setAberto] = useState(false);
  const [tipo, setTipo] = useState<TipoManifestacaoConclusiva>("confirmacao");
  const [justificativa, setJustificativa] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const escolhido = TIPOS.find((item) => item.valor === tipo) ?? TIPOS[0];
  const exigeJustificativa = tipo !== "confirmacao";
  const justificativaCurta = exigeJustificativa && justificativa.trim().length < 15;

  async function enviar() {
    if (exigeJustificativa && justificativaCurta) {
      // Barrar aqui evita um round-trip que a SEFAZ recusaria de qualquer forma
      // (xJust é obrigatório e tem tamanho mínimo no leiaute).
      setErro("A SEFAZ exige justificativa de 15 a 255 caracteres para este evento.");
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const [resultado] = await api.manifestarConclusiva(
        [documento.id],
        tipo,
        justificativa.trim()
      );
      if (resultado?.ok) {
        avisar({
          tom: "ok",
          titulo: "Manifestação registrada",
          descricao:
            "A SEFAZ foi avisada e vai liberar o XML completo. A busca roda sozinha nos próximos minutos.",
        });
        setAberto(false);
        setJustificativa("");
        aoConcluir();
      } else {
        setErro(resultado?.mensagem ?? "A SEFAZ recusou o evento.");
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível registrar a manifestação.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <Botao
        tamanho="sm"
        variante="secundaria"
        onClick={() => setAberto(true)}
        iconeEsquerda={<Icone nome="documento" className="h-3.5 w-3.5" />}
      >
        Manifestar operação
      </Botao>

      <DialogoConfirmacao
        aberto={aberto}
        aoFechar={() => setAberto(false)}
        aoConfirmar={enviar}
        titulo="Manifestação conclusiva"
        consequencia={
          <>
            O evento é enviado ao Ambiente Nacional <strong>em nome da empresa</strong> com o
            certificado A1, é irreversível e encerra a manifestação desta NF-e
            {documento.chave_acesso ? (
              <>
                {" "}
                (<span className="font-mono text-2xs">{chaveEmGrupos(documento.chave_acesso)}</span>)
              </>
            ) : null}
            .
          </>
        }
        impacto={
          <div className="space-y-3 text-left">
            <p className="text-sm text-tinta-suave">
              A Ciência da Operação não é mais aceita para esta nota
              {documento.manifestacao_cstat === "596" ? " (recusa 596 da SEFAZ)" : ""} porque passou
              dos 10 dias da autorização. Só um evento conclusivo libera o XML completo.
            </p>
            <GrupoRadio
              rotulo="O que aconteceu com a operação?"
              name="tipo-manifestacao"
              horizontal={false}
              valor={tipo}
              aoMudar={(valor) => setTipo(valor as TipoManifestacaoConclusiva)}
              opcoes={TIPOS.map((item) => ({ valor: item.valor, rotulo: item.rotulo }))}
            />
            <p className="text-xs leading-5 text-tinta-suave">{escolhido.ajuda}</p>
            {exigeJustificativa ? (
              <Area
                rotulo="Justificativa"
                descricao="Vai no XML do evento (xJust). A SEFAZ exige de 15 a 255 caracteres."
                value={justificativa}
                onChange={(evento) => setJustificativa(evento.target.value)}
                rows={3}
                maxLength={255}
                erro={justificativa && justificativaCurta ? "Escreva ao menos 15 caracteres." : undefined}
              />
            ) : null}
            {erro ? (
              <p role="alert" className="rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm text-erro">
                {erro}
              </p>
            ) : null}
          </div>
        }
        rotuloConfirmar="Registrar na SEFAZ"
        carregando={enviando}
        largura="larga"
      />
    </>
  );
}
