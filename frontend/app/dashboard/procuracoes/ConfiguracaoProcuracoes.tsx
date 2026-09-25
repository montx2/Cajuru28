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
import { Icone } from "@/components/ui/Icone";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

interface Props {
  aberta: boolean;
  aoFechar: () => void;
  aoSalvar: () => void;
}

/** Espelha `MIN_SEGREDO_INTEGRACAO` do contrato (backend/esquemas.py). */
const MIN_SEGREDO = 8;

/**
 * Área administrativa do módulo.
 *
 * Tudo que define *como* a autorização é pedida mora aqui, nunca no código:
 * quem é o outorgado, por quanto tempo vale, quais serviços, com que
 * antecedência alertar, quantos processos simultâneos e qual versão mínima do
 * Assinador é aceita. O escritório muda isso sem esperar deploy.
 */
export function ConfiguracaoProcuracoes({ aberta, aoFechar, aoSalvar }: Props) {
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const [salvando, setSalvando] = useState(false);
  const [rascunho, setRascunho] = useState<Record<string, unknown>>({});
  const [segredo, setSegredo] = useState("");

  const config = useRecurso(() => (aberta ? api.configuracaoProcuracoes() : Promise.resolve(null)), [aberta]);
  const modelos = useRecurso(() => (aberta ? api.modelosProcuracao() : Promise.resolve([])), [aberta]);
  const integracoes = useRecurso(() => (aberta ? api.integracoesProcuracao() : Promise.resolve([])), [aberta]);

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

  /**
   * A regra abaixo é a mesma do contrato (`CredencialEntrada`). Repeti-la
   * aqui não é duplicação inútil: é o que evita uma ida ao servidor para
   * receber um 422 por algo que dá para dizer na hora.
   */
  const erroSegredo =
    segredo.trim() && segredo.trim().length < MIN_SEGREDO
      ? `Faltam ${MIN_SEGREDO - segredo.trim().length} caractere(s): o token completo tem pelo menos ${MIN_SEGREDO}.`
      : "";
  const podeGravarCredencial = Boolean(segredo.trim()) && !erroSegredo;

  async function salvarIntegracao() {
    if (!podeGravarCredencial) return;
    setSalvando(true);
    try {
      await api.salvarIntegracaoProcuracao({ fonte: "integra_contador", segredo: segredo.trim() });
      avisar({ tom: "ok", titulo: "Credencial gravada", descricao: "O segredo é cifrado no cofre e nunca mais é exibido." });
      setSegredo("");
      integracoes.atualizar();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Credencial recusada", descricao: mensagemDoErro(erro) });
    } finally {
      setSalvando(false);
    }
  }

  async function sincronizar() {
    setSalvando(true);
    try {
      const resultado = await api.sincronizarProcuracoes("integra_contador");
      avisar({ tom: "ok", titulo: "Sincronização com Integra Contador", descricao: resultado.mensagem });
      aoSalvar();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Sincronização falhou", descricao: mensagemDoErro(erro) });
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
              ligado={Boolean(valor("processamento_automatico", false))}
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
              <Entrada
                rotulo="Por estação"
                type="number"
                min={1}
                max={5}
                numerico
                value={String(valor("max_jobs_por_agente", 1))}
                onChange={(evento) => setRascunho((a) => ({ ...a, max_jobs_por_agente: Number(evento.target.value) }))}
                disabled={somenteLeitura}
                descricao="Um operador não conduz dois portais ao mesmo tempo."
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
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Assinador SERPRO</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <Entrada
                rotulo="Versão mínima aceita"
                value={String(valor("assinador_versao_minima", "4.0.0"))}
                onChange={(evento) => setRascunho((a) => ({ ...a, assinador_versao_minima: evento.target.value }))}
                disabled={somenteLeitura}
                mono
              />
              <Alternador
                rotulo="Exigir Assinador apto"
                descricao="Desligar só faz sentido em ambiente de treinamento: sem Assinador o portal não aceita o certificado."
                ligado={Boolean(valor("assinador_exigido", true))}
                aoMudar={(ligado) => setRascunho((a) => ({ ...a, assinador_exigido: ligado }))}
                desabilitado={somenteLeitura}
                motivoDesabilitado={MOTIVO_SOMENTE_LEITURA}
              />
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Conformidade</h3>
            <Aviso tom="info" icone="cadeado" titulo={`Modo efetivo: ${atual.modo_efetivo}`}>
              {atual.fundamento_politica ||
                "A execução no Portal da Receita é assistida: o ato é praticado por pessoa autenticada, no ambiente oficial, sem encapsulamento."}
            </Aviso>
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Fontes de dados</h3>
            <Aviso tom="info" icone="importacao" titulo="A lista do Jettax 360 entra por importação">
              O painel do Jettax 360 não publica API de procurações — e o módulo não guarda credencial de terceiro para
              essa tela. O caminho é <span className="font-medium">Importar lista</span> na tela de Procurações: copia-se
              o que está na tela (ou o CSV exportado) e o resultado é dado governado, com idempotência e histórico — o
              mesmo efeito de uma consulta, sem depender de endpoint que não existe.
            </Aviso>
            <ul className="space-y-2">
              {(integracoes.dados ?? []).map((item) => (
                <li key={item.fonte} className="flex flex-wrap items-center justify-between gap-2 rounded-controle border border-borda-controle p-2.5">
                  <div className="min-w-0">
                    <p className="text-sm text-tinta">{item.rotulo}</p>
                    <p className="text-xs text-tinta-suave">
                      {item.configurado ? "credencial no cofre" : "não configurada"}
                      {item.ultimo_erro ? <span className="text-erro"> · {item.ultimo_erro}</span> : null}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {item.configurado ? (
                      <>
                        <Botao variante="sutil" tamanho="sm" disabled={salvando} onClick={() => api.testarIntegracaoProcuracao(item.fonte).then((r) => avisar({ tom: r.ok ? "ok" : "erro", titulo: item.rotulo, descricao: r.mensagem }))}>
                          Testar
                        </Botao>
                        <Botao variante="sutil" tamanho="sm" disabled={salvando || somenteLeitura} onClick={sincronizar}>
                          Sincronizar
                        </Botao>
                      </>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>

            <div className="grid gap-3 rounded-controle border border-borda-controle p-3 sm:grid-cols-2">
              <Entrada
                rotulo="Token do Integra Contador (SERPRO)"
                type="password"
                autoComplete="off"
                value={segredo}
                onChange={(evento) => setSegredo(evento.target.value)}
                disabled={somenteLeitura}
                descricao={`Única integração remota do módulo. Cifrada no cofre; nunca volta na API. Mínimo de ${MIN_SEGREDO} caracteres.`}
                erro={erroSegredo || null}
              />
              <div className="flex items-end">
                <Botao
                  variante="secundaria"
                  tamanho="sm"
                  carregando={salvando}
                  disabled={somenteLeitura || !podeGravarCredencial}
                  title={
                    somenteLeitura
                      ? MOTIVO_SOMENTE_LEITURA
                      : erroSegredo || (!segredo.trim() ? "Informe o token do Integra Contador" : undefined)
                  }
                  onClick={salvarIntegracao}
                  iconeEsquerda={<Icone nome="chave" className="h-4 w-4" />}
                >
                  Gravar credencial
                </Botao>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </Modal>
  );
}
