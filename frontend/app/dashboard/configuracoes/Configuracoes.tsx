"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { bytesParaTexto, dataHora, numero, plural } from "@/lib/format";
import { estadoDeIntegracao } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA, ehAdmin } from "@/lib/papel";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Abas, type Aba } from "@/components/ui/Abas";
import { Alternador, Entrada } from "@/components/ui/Campo";
import { Aviso } from "@/components/ui/Aviso";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Dado } from "@/components/ui/Dado";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { useToast } from "@/components/ui/Toast";
import { ROTULO_CATEGORIA_ALERTA, type ResetGeralResposta } from "@/lib/types";

const ABAS = ["ambiente", "integracoes", "alertas", "dados"];

/**
 * Configurações: ambiente, integrações, alertas e zona de risco.
 *
 * Credencial de integração é escrita e nunca lida de volta — a tela mostra
 * "configurado" ou "não configurado", nunca o token. O reset geral mora aqui com
 * confirmação digitada porque apaga acervo, certificados e integrações.
 */
export function Configuracoes() {
  const { definir, ler } = useUrlEstado();
  const { papel, somenteLeitura } = useSessao();
  const aba = ABAS.includes(ler("aba")) ? ler("aba") : "ambiente";

  const sistema = useRecurso(() => api.infoSistema(), []);
  const saude = useRecurso(() => api.saudeDetalhada(), []);
  useSinalizarAtualizacao(sistema.atualizando || saude.atualizando);

  const abas: Aba[] = [
    { valor: "ambiente", rotulo: "Ambiente", icone: "configuracoes" },
    { valor: "integracoes", rotulo: "Integrações", icone: "webhook" },
    { valor: "alertas", rotulo: "Alertas", icone: "sino" },
    { valor: "dados", rotulo: "Zona de risco", icone: "risco" },
  ];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Configurações"
        descricao="Como esta instalação está montada, o que ela conversa por fora e o que apaga dados."
        acoes={
          <Botao
            variante="sutil"
            onClick={() => {
              sistema.atualizar();
              saude.atualizar();
            }}
            carregando={sistema.atualizando}
            iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
          >
            Atualizar
          </Botao>
        }
      />

      <Abas rotulo="Seções de configuração" idBase="aba-configuracoes" abas={abas} valor={aba} aoMudar={(valor) => definir({ aba: valor })} />

      {aba === "ambiente" ? <AbaAmbiente /> : null}
      {aba === "integracoes" ? <AbaIntegracoes admin={ehAdmin(papel)} somenteLeitura={somenteLeitura} /> : null}
      {aba === "alertas" ? <AbaAlertas admin={ehAdmin(papel)} /> : null}
      {aba === "dados" ? <AbaDados admin={ehAdmin(papel)} /> : null}
    </div>
  );
}

function AbaAmbiente() {
  const sistema = useRecurso(() => api.infoSistema(), []);
  const saude = useRecurso(() => api.saudeDetalhada(), []);

  if (sistema.carregando || saude.carregando) return <EsqueletoBloco linhas={8} />;

  return (
    <div className="space-y-4">
      {saude.erro ? (
        <EstadoErro erro={saude.erro} aoTentarNovamente={saude.atualizar} contexto="ler a saúde detalhada do ambiente" />
      ) : saude.dados ? (
        <Cartao
          titulo="Diagnóstico"
          descricao="Leitura de /sistema/saude-detalhada"
          acoes={<BotaoLink variante="sutil" tamanho="sm" href="/dashboard/saude">Abrir Saúde</BotaoLink>}
        >
          <div className="flex flex-wrap items-center gap-2">
            <IndicadorEstado
              tom={saude.dados.ok ? "ok" : "erro"}
              rotulo={saude.dados.ok ? "Ambiente operacional" : `${numero(saude.dados.problemas.length)} problemas`}
              icone={saude.dados.ok ? "verificar-circulo" : "risco"}
            />
            <IndicadorEstado tom={saude.dados.banco_ok ? "ok" : "erro"} rotulo={saude.dados.banco_ok ? "Banco conectado" : "Banco sem conexão"} icone="banco" />
            {saude.dados.disco_livre_bytes !== null ? (
              <IndicadorEstado
                tom={saude.dados.disco_livre_bytes < 1024 ** 3 ? "erro" : "ok"}
                rotulo={`${bytesParaTexto(saude.dados.disco_livre_bytes)} livres`}
                icone="disco"
              />
            ) : null}
          </div>
          {saude.dados.problemas.length > 0 ? (
            <ul className="mt-3 list-disc space-y-1 pl-4 text-sm text-erro">
              {saude.dados.problemas.map((problema) => (
                <li key={problema}>{problema}</li>
              ))}
            </ul>
          ) : null}
        </Cartao>
      ) : null}

      {sistema.erro ? (
        <EstadoErro erro={sistema.erro} aoTentarNovamente={sistema.atualizar} contexto="ler as informações do sistema" />
      ) : sistema.dados ? (
        <Cartao titulo="Instalação" descricao="Somente leitura: estas definições vêm do compose e das variáveis de ambiente">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
            <Dado rotulo="Modo" valor={sistema.dados.modo} />
            <Dado rotulo="Banco" valor={sistema.dados.banco} mono />
            <Dado rotulo="Pasta de dados" valor={sistema.dados.dados_dir} mono />
            <Dado rotulo="Fila" valor={sistema.dados.fila.modo} mono />
            <Dado rotulo="Hora do servidor" valor={dataHora(sistema.dados.hora_do_servidor)} />
            <Dado
              rotulo="Webhook"
              valor={sistema.dados.webhook?.configurado ? `nível ${sistema.dados.webhook.nivel_minimo} · ${numero(sistema.dados.webhook.intervalo_minutos)} min` : "não configurado"}
              tom={sistema.dados.webhook?.configurado ? undefined : "espera"}
            />
          </dl>

          <div className="mt-4 border-t border-traco pt-3">
            <p className="mb-1.5 text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">Tarefas agendadas</p>
            {Object.keys(sistema.dados.fila.agenda).length === 0 ? (
              <p className="text-sm text-tinta-fraca">Nenhuma tarefa agendada — a captura automática depende delas.</p>
            ) : (
              <ul className="grid gap-1 sm:grid-cols-2">
                {Object.entries(sistema.dados.fila.agenda).map(([chave, item]) => (
                  <li key={chave} className="flex items-baseline justify-between gap-3 rounded-controle border border-traco px-3 py-1.5 text-sm">
                    <span className="min-w-0 truncate text-tinta">{chave}</span>
                    <span className="nums flex-none text-xs text-tinta-suave">{item.tarefa ?? "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Cartao>
      ) : null}
    </div>
  );
}

function AbaIntegracoes({ admin, somenteLeitura }: { admin: boolean; somenteLeitura: boolean }) {
  const { avisar } = useToast();
  const accessorias = useRecurso(() => api.statusAcessorias(), []);
  const jettax = useRecurso(() => api.statusJettax(), []);

  const [tokenAcessorias, setTokenAcessorias] = useState("");
  const [baseAcessorias, setBaseAcessorias] = useState("");
  const [tokenJettax, setTokenJettax] = useState("");
  const [baseJettax, setBaseJettax] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [confirmandoRemocao, setConfirmandoRemocao] = useState(false);

  const bloqueado = somenteLeitura || !admin;
  const motivoBloqueio = !admin ? "Somente administrador altera credenciais de integração." : MOTIVO_SOMENTE_LEITURA;

  async function executar(chave: string, acao: () => Promise<{ titulo: string; descricao?: string; tom?: "ok" | "espera" | "erro" }>) {
    setOcupado(chave);
    try {
      const resultado = await acao();
      avisar({ tom: resultado.tom ?? "ok", titulo: resultado.titulo, descricao: resultado.descricao });
      accessorias.atualizar();
      jettax.atualizar();
    } catch (falha) {
      avisar({ tom: "erro", titulo: "A ação não foi concluída", descricao: mensagemDoErro(falha, chave) });
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div className="space-y-4">
      {bloqueado ? (
        <Aviso tom="info" icone="cadeado" titulo="Leitura liberada, escrita restrita">
          {motivoBloqueio} Os status abaixo refletem o que está configurado no servidor.
        </Aviso>
      ) : null}

      <Cartao
        titulo="Acessórias"
        descricao="Cadastro de empresas por CNPJ e credencial cifrada no servidor"
        acoes={
          accessorias.dados ? (
            <IndicadorEstado {...estadoDeIntegracao(accessorias.dados.configurado ? "ok" : null)} />
          ) : undefined
        }
      >
        {accessorias.carregando ? (
          <EsqueletoBloco linhas={4} />
        ) : accessorias.erro ? (
          <EstadoErro erro={accessorias.erro} aoTentarNovamente={accessorias.atualizar} contexto="ler o status da integração Acessórias" />
        ) : accessorias.dados ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Dado rotulo="Situação" valor={accessorias.dados.configurado ? "Configurada" : "Sem credencial"} tom={accessorias.dados.configurado ? undefined : "espera"} />
              <Dado rotulo="Base" valor={accessorias.dados.base_url || "—"} mono />
              <Dado rotulo="Última sincronização" valor={accessorias.dados.ultima_sincronizacao_em ? dataHora(accessorias.dados.ultima_sincronizacao_em) : "nunca"} />
              <Dado rotulo="Token" valor={accessorias.dados.configurado ? "armazenado no servidor" : "ausente"} />
            </dl>

            <div className="grid gap-3 border-t border-traco pt-3 sm:grid-cols-2">
              <Entrada
                rotulo="Token"
                type="password"
                autoComplete="off"
                value={tokenAcessorias}
                onChange={(evento) => setTokenAcessorias(evento.target.value)}
                disabled={bloqueado}
                descricao={accessorias.dados.configurado ? "Informe só para trocar o token atual." : "O token é cifrado ao ser gravado."}
              />
              <Entrada
                rotulo="Base URL"
                value={baseAcessorias || accessorias.dados.base_url}
                onChange={(evento) => setBaseAcessorias(evento.target.value)}
                disabled={bloqueado}
                placeholder="https://api.acessorias.com.br"
                descricao="Endereço da API do parceiro."
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Botao
                variante="secundaria"
                onClick={() =>
                  executar("salvar a credencial Acessórias", async () => {
                    await api.salvarCredencialAcessorias(tokenAcessorias, baseAcessorias || accessorias.dados?.base_url || "");
                    setTokenAcessorias("");
                    return { titulo: "Credencial Acessórias salva" };
                  })
                }
                carregando={ocupado === "salvar a credencial Acessórias"}
                disabled={bloqueado || (!tokenAcessorias && !baseAcessorias)}
                title={bloqueado ? motivoBloqueio : "Salva token e base sem exibir o valor antigo"}
              >
                Salvar credencial
              </Botao>
              <Botao
                variante="sutil"
                onClick={() =>
                  executar("testar a integração Acessórias", async () => {
                    const resultado = await api.testarAcessorias();
                    return { titulo: resultado.ok ? "Acessórias respondeu" : "Acessórias não respondeu", descricao: resultado.mensagem, tom: resultado.ok ? "ok" : "erro" };
                  })
                }
                carregando={ocupado === "testar a integração Acessórias"}
              >
                Testar conexão
              </Botao>
              <Botao
                variante="sutil"
                onClick={() =>
                  executar("sincronizar empresas das Acessórias", async () => {
                    const resultado = await api.sincronizarEmpresasAcessorias();
                    return {
                      titulo: `${numero(resultado.criadas)} ${plural(resultado.criadas, "empresa criada", "empresas criadas")}`,
                      descricao: `${numero(resultado.atualizadas)} atualizadas · ${numero(resultado.ignoradas)} ignoradas · ${numero(resultado.invalidas)} inválidas`,
                      tom: resultado.invalidas > 0 ? "espera" : "ok",
                    };
                  })
                }
                carregando={ocupado === "sincronizar empresas das Acessórias"}
                disabled={bloqueado || !accessorias.dados.configurado}
                title={accessorias.dados.configurado ? undefined : "Salve a credencial antes de sincronizar"}
              >
                Sincronizar empresas
              </Botao>
            </div>
          </div>
        ) : null}
      </Cartao>

      <Cartao
        titulo="Jettax"
        descricao="Registro por empresa, importação de NFS-e e NF-e"
        acoes={jettax.dados ? <IndicadorEstado {...estadoDeIntegracao(jettax.dados.configurado ? jettax.dados.saude : null)} /> : undefined}
      >
        {jettax.carregando ? (
          <EsqueletoBloco linhas={4} />
        ) : jettax.erro ? (
          <EstadoErro erro={jettax.erro} aoTentarNovamente={jettax.atualizar} contexto="ler o status da integração Jettax" />
        ) : jettax.dados ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
              <Dado rotulo="Situação" valor={jettax.dados.configurado ? "Configurada" : "Sem credencial"} tom={jettax.dados.configurado ? undefined : "espera"} />
              <Dado rotulo="Saúde" valor={jettax.dados.saude} tom={jettax.dados.saude === "ok" ? undefined : "espera"} />
              <Dado rotulo="Base" valor={jettax.dados.base_url || "—"} mono />
              <Dado rotulo="Empresas" valor={`${numero(jettax.dados.empresas_registradas)} registradas · ${numero(jettax.dados.empresas_ativas)} ativas`} />
            </dl>
            {jettax.dados.mensagem ? <p className="text-sm text-tinta-suave">{jettax.dados.mensagem}</p> : null}

            <div className="grid gap-3 border-t border-traco pt-3 sm:grid-cols-2">
              <Entrada
                rotulo="Token"
                type="password"
                autoComplete="off"
                value={tokenJettax}
                onChange={(evento) => setTokenJettax(evento.target.value)}
                disabled={bloqueado}
                descricao="Use o token da API Morfeu. Pode colar o valor puro ou a linha “Authorization: Bearer …”; o prefixo é removido antes de cifrar."
              />
              <Entrada
                rotulo="Base URL"
                value={baseJettax || jettax.dados.base_url}
                onChange={(evento) => setBaseJettax(evento.target.value)}
                disabled={bloqueado}
                placeholder="https://morfeu-api.jettax.com.br"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Botao
                variante="secundaria"
                onClick={() =>
                  executar("salvar a credencial Jettax", async () => {
                    await api.salvarCredencialJettax(tokenJettax, baseJettax || jettax.dados?.base_url || "");
                    setTokenJettax("");
                    await jettax.atualizar();
                    return { titulo: "Credencial Jettax salva", descricao: "O resultado da verificação autenticada aparece no status acima." };
                  })
                }
                carregando={ocupado === "salvar a credencial Jettax"}
                disabled={bloqueado || (!tokenJettax && !baseJettax)}
                title={bloqueado ? motivoBloqueio : undefined}
              >
                Salvar credencial
              </Botao>
              <Botao
                variante="sutil"
                onClick={() =>
                  executar("testar a integração Jettax", async () => {
                    const resultado = await api.testarJettax();
                    return { titulo: `Jettax: ${resultado.status}`, descricao: resultado.mensagem, tom: resultado.status === "ok" ? "ok" : "erro" };
                  })
                }
                carregando={ocupado === "testar a integração Jettax"}
              >
                Testar conexão
              </Botao>
              <BotaoLink variante="sutil" href="/dashboard/empresas">
                Registrar empresas
              </BotaoLink>
              {jettax.dados.configurado && !bloqueado ? (
                <Botao variante="perigo-sutil" className="ml-auto" onClick={() => setConfirmandoRemocao(true)}>
                  Remover credencial
                </Botao>
              ) : null}
            </div>
          </div>
        ) : null}
      </Cartao>

      <DialogoConfirmacao
        aberto={confirmandoRemocao}
        aoFechar={() => setConfirmandoRemocao(false)}
        aoConfirmar={() =>
          executar("remover a credencial Jettax", async () => {
            await api.removerCredencialJettax();
            setConfirmandoRemocao(false);
            return { titulo: "Credencial Jettax removida", descricao: "As importações por esta integração param imediatamente.", tom: "espera" };
          })
        }
        tom="perigo"
        titulo="Remover credencial Jettax"
        consequencia="A integração deixa de funcionar para todas as empresas: nenhuma importação Jettax será disparada."
        impacto="Registros já importados permanecem no acervo. Para voltar, é preciso salvar um token novo."
        rotuloConfirmar="Remover credencial"
      />
    </div>
  );
}

function AbaAlertas({ admin }: { admin: boolean }) {
  const { avisar } = useToast();
  const sistema = useRecurso(() => api.infoSistema(), []);
  const [testando, setTestando] = useState(false);

  async function testarWebhook() {
    setTestando(true);
    try {
      const resultado = await api.testarWebhook();
      avisar({ tom: resultado.ok ? "ok" : "erro", titulo: resultado.ok ? "Webhook respondeu" : "O webhook não respondeu", descricao: resultado.detalhe });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível testar o webhook", descricao: mensagemDoErro(falha, "testar o webhook") });
    } finally {
      setTestando(false);
    }
  }

  const webhook = sistema.dados?.webhook;

  return (
    <div className="space-y-4">
      <Cartao
        titulo="Webhook de alertas"
        descricao="Para onde os alertas são empurrados assim que aparecem"
        acoes={
          webhook?.configurado ? <IndicadorEstado tom="ok" rotulo="Configurado" icone="verificar-circulo" /> : <IndicadorEstado tom="espera" rotulo="Não configurado" icone="info" />
        }
      >
        {sistema.carregando ? (
          <EsqueletoBloco linhas={3} />
        ) : sistema.erro ? (
          <EstadoErro erro={sistema.erro} aoTentarNovamente={sistema.atualizar} contexto="ler a configuração de alertas" />
        ) : (
          <div className="space-y-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
              <Dado rotulo="Situação" valor={webhook?.configurado ? "Configurado" : "Sem destino"} tom={webhook?.configurado ? undefined : "espera"} />
              <Dado rotulo="Nível mínimo" valor={webhook?.nivel_minimo ?? "—"} />
              <Dado rotulo="Intervalo" valor={webhook ? `${numero(webhook.intervalo_minutos)} min` : "—"} />
            </dl>
            <p className="text-sm text-tinta-suave">
              A URL e o segredo do webhook são definidos por variável de ambiente no servidor — não por esta tela. Alterar o nível mínimo muda quais
              alertas saem do NotasFlow: abaixo dele, o item continua visível em <Link href="/dashboard/atencao" className="font-medium text-acento underline-offset-4 hover:underline">Precisa da sua atenção</Link>.
            </p>
            <Botao variante="secundaria" onClick={testarWebhook} carregando={testando} disabled={!admin} title={admin ? "Envia um alerta de teste para o destino configurado" : "Somente administrador testa o webhook"}>
              Enviar alerta de teste
            </Botao>
          </div>
        )}
      </Cartao>

      <Cartao titulo="O que vira alerta" descricao="Categorias avaliadas a cada varredura, do crítico ao informativo">
        <ul className="grid gap-2 sm:grid-cols-2">
          {Object.entries(ROTULO_CATEGORIA_ALERTA).map(([categoria, rotulo]) => (
            <li key={categoria} className="flex items-start justify-between gap-3 rounded-controle border border-traco px-3 py-2">
              <span className="min-w-0">
                <span className="block text-sm text-tinta">{rotulo}</span>
                <span className="block text-xs text-tinta-suave">{DESCRICAO_CATEGORIA[categoria] ?? "Verificado a cada varredura automática."}</span>
              </span>
              <Etiqueta tom="neutro">{categoria}</Etiqueta>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-tinta-suave">
          Espera de janela da SEFAZ e cooldown aparecem em âmbar, nunca em vermelho: não é falha, é o ritmo imposto pelo fisco.
        </p>
      </Cartao>
    </div>
  );
}

const DESCRICAO_CATEGORIA: Record<string, string> = {
  certificado: "A1 vencido, ausente ou falhando na autenticação — a captura da empresa para.",
  cadastro: "Empresa sem UF, inativa ou sem tipos definidos para sincronizar.",
  sefaz: "Rejeição, bloqueio ou janela de espera imposta pela SEFAZ.",
  distribuicao: "Documento saiu do horizonte de distribuição: risco de perda definitiva.",
  sincronismo: "Cursor (NSU) parado, pendência acumulada ou dias sem varrer.",
  xml: "Documentos recebidos em resumo, sem o XML completo.",
  execucao: "Execuções com erro, travadas ou com tentativas repetidas.",
  sistema: "Banco, disco, fila ou backup fora do esperado.",
};

function AbaDados({ admin }: { admin: boolean }) {
  const { avisar } = useToast();
  const [confirmar, setConfirmar] = useState(false);
  const [removerIntegracoes, setRemoverIntegracoes] = useState(false);
  const [forcar, setForcar] = useState(false);
  const [executando, setExecutando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<ResetGeralResposta | null>(null);

  async function resetar() {
    setExecutando(true);
    setErro(null);
    try {
      const resposta = await api.resetGeral({ confirmar: "APAGAR TUDO", remover_integracoes: removerIntegracoes, forcar });
      setResultado(resposta);
      setConfirmar(false);
      avisar({
        tom: "espera",
        titulo: "Reset geral executado",
        descricao: `${numero(resposta.documentos)} documentos e ${numero(resposta.empresas)} empresas apagados`,
      });
    } catch (falha) {
      setErro(mensagemDoErro(falha, "executar o reset geral"));
    } finally {
      setExecutando(false);
    }
  }

  if (!admin) {
    return (
      <EstadoVazio
        titulo="Zona de risco restrita a administradores"
        instrucao="Operações que apagam dados em massa não ficam disponíveis para outros papéis — nem desabilitadas: elas não aparecem."
        icone="cadeado"
      />
    );
  }

  return (
    <div className="space-y-4">
      {resultado ? (
        <Aviso tom="espera" icone="risco" titulo="Reset geral executado" aoFechar={() => setResultado(null)}>
          <span className="nums">
            {numero(resultado.empresas)} empresas · {numero(resultado.documentos)} documentos · {numero(resultado.certificados)} certificados ·{" "}
            {numero(resultado.execucoes)} execuções · {numero(resultado.sincronizacoes)} sincronizações · {numero(resultado.arquivos_removidos)} arquivos
            removidos{resultado.integracoes > 0 ? ` · ${numero(resultado.integracoes)} integrações` : ""}.
          </span>{" "}
          Comece recadastrando as empresas e enviando os certificados A1.
        </Aviso>
      ) : null}

      <Cartao titulo="Reset geral" descricao="Apaga o acervo desta instalação e volta ao estado inicial" tomFaixa="bg-erro">
        <div className="space-y-4">
          <p className="max-w-leitura text-sm leading-6 text-tinta">
            Esta operação existe para reinstalar o NotasFlow sem reconstruir o banco na mão. Ela apaga empresas, documentos, certificados, execuções e
            sincronizações — e remove os arquivos XML do disco. Não há como desfazer.
          </p>

          <div className="space-y-3 rounded-controle border border-erro/40 bg-erro-tenue p-3">
            <Alternador
              rotulo="Remover também as credenciais de integração"
              descricao="Acessórias e Jettax voltam a “não configuradas”."
              ligado={removerIntegracoes}
              aoMudar={setRemoverIntegracoes}
            />
            <Alternador
              rotulo="Forçar mesmo com tarefas em andamento"
              descricao="Sem isto, o reset é recusado se houver execução rodando."
              ligado={forcar}
              aoMudar={setForcar}
            />
          </div>

          {erro ? (
            <p role="alert" className="text-sm text-erro">
              {erro}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="perigo" onClick={() => setConfirmar(true)} iconeEsquerda={<Icone nome="risco" className="h-4 w-4" />}>
              Executar reset geral
            </Botao>
            <BotaoLink variante="sutil" href="/dashboard/saude">
              Ver saúde antes
            </BotaoLink>
          </div>
        </div>
      </Cartao>

      <DialogoConfirmacao
        aberto={confirmar}
        aoFechar={() => setConfirmar(false)}
        aoConfirmar={resetar}
        carregando={executando}
        erro={erro}
        tom="perigo"
        largura="media"
        titulo="Apagar todos os dados desta instalação"
        consequencia="Empresas, documentos, certificados, execuções e sincronizações são apagados do banco, e os arquivos XML são removidos do disco."
        impacto={
          <span>
            Depois disto o NotasFlow volta ao estado de instalação nova: nenhuma captura roda até haver empresa com certificado A1.{" "}
            {removerIntegracoes ? "As credenciais de Acessórias e Jettax também serão removidas." : "Credenciais de integração serão mantidas."}
          </span>
        }
        exigirTexto="APAGAR TUDO"
        rotuloConfirmar="Apagar tudo"
      />
    </div>
  );
}

