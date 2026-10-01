"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useRecurso } from "@/lib/useRecurso";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { Alternador, Entrada } from "@/components/ui/Campo";
import { Dado } from "@/components/ui/Dado";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

interface Props {
  aberta: boolean;
  aoFechar: () => void;
  aoSalvar: () => void;
}

/**
 * Área administrativa do módulo.
 *
 * Tudo que define *como* a autorização é pedida mora aqui, nunca no código:
 * quem é o outorgado, por quanto tempo vale, quais serviços, com que
 * antecedência alertar e quantos processos simultâneos. O escritório muda
 * isso sem esperar deploy.
 */
export function ConfiguracaoProcuracoes({ aberta, aoFechar, aoSalvar }: Props) {
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const [salvando, setSalvando] = useState(false);
  const [rascunho, setRascunho] = useState<Record<string, unknown>>({});

  const config = useRecurso(() => (aberta ? api.configuracaoProcuracoes() : Promise.resolve(null)), [aberta]);
  const modelos = useRecurso(() => (aberta ? api.modelosProcuracao() : Promise.resolve([])), [aberta]);

  useEffect(() => {
    if (config.dados) setRascunho({});
  }, [config.dados]);

  const atual = config.dados;
  const valor = <T,>(campo: string, padrao: T): T =>
    (rascunho[campo] as T) ?? ((atual as unknown as Record<string, T>)?.[campo] ?? padrao);

  async function salvar() {
    if (!atual) return;
    setSalvando(true);
    try {
      await api.salvarConfiguracaoProcuracoes({ ...atual, ...rascunho });
      avisar({ tom: "ok", titulo: "Configuração salva" });
      config.atualizar();
      aoSalvar();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Não foi possível salvar", descricao: mensagemDoErro(erro) });
    } finally {
      setSalvando(false);
    }
  }

  const modeloPadrao = (modelos.dados ?? []).find((item) => item.padrao);

  return (
    <Modal
      aberto={aberta}
      aoFechar={aoFechar}
      titulo="Configurações · Procurações RFB"
      descricao="Nada aqui está fixo no código: vigência, serviços, prazos e limites são do escritório."
      largura="larga"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={aoFechar}>
            Fechar
          </Botao>
          <Botao
            variante="primaria"
            carregando={salvando}
            disabled={somenteLeitura}
            title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
            onClick={salvar}
          >
            Salvar
          </Botao>
        </div>
      }
    >
      {config.carregando ? <p className="text-sm text-tinta-suave">Carregando…</p> : null}

      {atual ? (
        <div className="space-y-6">
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Quem recebe a autorização</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <Entrada
                rotulo="CNPJ/CPF da contabilidade"
                value={String(valor("outorgado_documento", ""))}
                onChange={(evento) => setRascunho((atualizado) => ({ ...atualizado, outorgado_documento: evento.target.value }))}
                disabled={somenteLeitura}
                mono
                descricao="É o outorgado de toda autorização criada pelo módulo."
              />
              <Entrada
                rotulo="Nome da contabilidade"
                value={String(valor("outorgado_nome", ""))}
                onChange={(evento) => setRascunho((atualizado) => ({ ...atualizado, outorgado_nome: evento.target.value }))}
                disabled={somenteLeitura}
              />
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Modelo aplicado</h3>
            {modeloPadrao ? (
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Dado rotulo="Modelo" valor={modeloPadrao.nome} />
                <Dado rotulo="Vigência" valor={`${modeloPadrao.vigencia_meses} meses`} contexto="teto legal: 60" />
                <Dado
                  rotulo="Serviços"
                  valor={modeloPadrao.escopo_servicos === "ALL" ? "Todos" : `${modeloPadrao.servicos.length} selecionados`}
                />
              </dl>
            ) : (
              <p className="text-xs text-tinta-suave">Nenhum modelo padrão — o módulo usa 60 meses e todos os serviços.</p>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Automação</h3>
            <Alternador
              rotulo="Montar a fila automaticamente"
              descricao="O agendador avalia a carteira e cria os processos. A execução no portal continua sendo humana."
              ligado={Boolean(valor("processamento_automatico", true))}
              aoMudar={(ligado) => setRascunho((atualizado) => ({ ...atualizado, processamento_automatico: ligado }))}
              desabilitado={somenteLeitura}
              motivoDesabilitado={MOTIVO_SOMENTE_LEITURA}
            />
            <Alternador
              rotulo="Sincronizar com as fontes configuradas"
              descricao="Lê a situação das autorizações uma vez por dia, no horário escolhido."
              ligado={Boolean(valor("sincronizacao_automatica", true))}
              aoMudar={(ligado) => setRascunho((atualizado) => ({ ...atualizado, sincronizacao_automatica: ligado }))}
              desabilitado={somenteLeitura}
              motivoDesabilitado={MOTIVO_SOMENTE_LEITURA}
            />
            <div className="grid gap-3 sm:grid-cols-3">
              <Entrada
                rotulo="Hora da sincronização"
                type="number"
                min={0}
                max={23}
                numerico
                value={String(valor("hora_sincronizacao", 6))}
                onChange={(evento) => setRascunho((a) => ({ ...a, hora_sincronizacao: Number(evento.target.value) }))}
                disabled={somenteLeitura}
              />
              <Entrada
                rotulo="Processos simultâneos"
                type="number"
                min={1}
                max={20}
                numerico
                value={String(valor("max_jobs_simultaneos", 2))}
                onChange={(evento) => setRascunho((a) => ({ ...a, max_jobs_simultaneos: Number(evento.target.value) }))}
                disabled={somenteLeitura}
                descricao="No escritório inteiro."
              />
            </div>
            <Entrada
              rotulo="Alertar com antecedência de (dias)"
              value={String(valor("alerta_dias", "30,60,90"))}
              onChange={(evento) => setRascunho((a) => ({ ...a, alerta_dias: evento.target.value }))}
              disabled={somenteLeitura}
              descricao="Separe por vírgula. Vale para vencimento de autorização e de certificado."
            />
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Conformidade</h3>
            <Aviso tom="info" icone="cadeado" titulo={`Modo efetivo: ${atual.modo_efetivo}`}>
              {atual.fundamento_politica ||
                "A execução no Portal da Receita é assistida: o ato é praticado por pessoa autenticada, no ambiente oficial, sem encapsulamento."}
            </Aviso>
          </section>

        </div>
      ) : null}
    </Modal>
  );
}
