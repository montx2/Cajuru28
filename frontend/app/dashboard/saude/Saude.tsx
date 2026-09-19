"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { bytesParaTexto, dataHora, numero, plural, tempoRelativo } from "@/lib/format";
import { estadoDoBackup, estadoDoComponente } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA, ehAdmin } from "@/lib/papel";
import { usePolling } from "@/lib/usePolling";
import { useRecurso } from "@/lib/useRecurso";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Dado } from "@/components/ui/Dado";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { DataHora } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { BarraProgresso } from "@/components/ui/Progresso";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import type { BackupRegistro } from "@/lib/types";

/**
 * Saúde do ambiente: o que está de pé, o que degrada e se o backup existe.
 *
 * A regra de cor aqui é a mesma do resto do produto: janela da SEFAZ e espera são
 * âmbar, nunca vermelho — vermelho é só o que parou de funcionar. Backup
 * atrasado é erro porque a perda é irreversível.
 */
export function Saude() {
  const { avisar } = useToast();
  const { papel, somenteLeitura } = useSessao();
  const agora = useAgora();
  const [executandoBackup, setExecutandoBackup] = useState<number | null>(null);

  const saude = useRecurso(() => api.saudeDetalhada(), []);
  const sistema = useRecurso(() => api.infoSistema(), []);
  const backups = useRecurso(() => api.backups(), []);
  const painel = useRecurso(() => api.painelOperacional(), []);

  useSinalizarAtualizacao(saude.atualizando || backups.atualizando || painel.atualizando);
  // Ambiente muda devagar: 60 s basta, e a aba oculta pausa a consulta.
  usePolling(() => {
    saude.atualizar();
    backups.atualizar();
    painel.atualizar();
  }, 60_000);

  function recarregar() {
    saude.atualizar();
    sistema.atualizar();
    backups.atualizar();
    painel.atualizar();
  }

  async function executarBackup() {
    setExecutandoBackup(0);
    try {
      const registro = await api.executarBackup();
      avisar({ tom: registro.status === "ok" ? "ok" : "espera", titulo: `Backup ${registro.status === "ok" ? "concluído" : "em andamento"}`, descricao: `${numero(registro.empresas)} empresas · ${numero(registro.documentos)} documentos` });
      backups.atualizar();
    } catch (falha) {
      avisar({ tom: "erro", titulo: "O backup não rodou", descricao: mensagemDoErro(falha, "executar o backup") });
    } finally {
      setExecutandoBackup(null);
    }
  }

  async function testarBackup(registro: BackupRegistro) {
    setExecutandoBackup(registro.id);
    try {
      const resultado = await api.testarBackup(registro.id);
      avisar({ tom: resultado.ok ? "ok" : "erro", titulo: resultado.ok ? "Restauração testada com sucesso" : "O teste de restauração falhou", descricao: resultado.detalhe });
      backups.atualizar();
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível testar o backup", descricao: mensagemDoErro(falha, "testar a restauração") });
    } finally {
      setExecutandoBackup(null);
    }
  }

  const dados = saude.dados;
  const componentes = painel.dados?.componentes ?? [];
  const problemas = dados?.problemas ?? [];

  const indicadores: KpiProps[] = [
    {
      rotulo: "Situação geral",
      valor: dados ? (dados.ok ? "Operacional" : `${numero(problemas.length)} problemas`) : "—",
      tom: dados ? (dados.ok ? "ok" : "erro") : "neutro",
      carregando: saude.carregando,
      dica: "Leitura de /sistema/saude-detalhada: banco, disco e fila.",
    },
    { rotulo: "Banco de dados", valor: dados ? (dados.banco_ok ? "Conectado" : "Sem conexão") : "—", tom: dados?.banco_ok ? "ok" : "erro", carregando: saude.carregando },
    {
      rotulo: "Disco livre",
      valor: dados?.disco_livre_bytes !== null && dados?.disco_livre_bytes !== undefined ? bytesParaTexto(dados.disco_livre_bytes) : "—",
      tom: dados && dados.disco_livre_bytes !== null && dados.disco_livre_bytes < 1024 ** 3 ? "erro" : "neutro",
      contexto: dados?.pasta_dados ? `pasta ${dados.pasta_dados}` : undefined,
      carregando: saude.carregando,
    },
    {
      rotulo: "Backups",
      valor: backups.dados ? (backups.dados.saude.atrasado ? "Atrasado" : "Em dia") : "—",
      tom: backups.dados ? (backups.dados.saude.atrasado ? "erro" : "ok") : "neutro",
      contexto: backups.dados?.saude.ultimo_ok_em ? `último ok ${tempoRelativo(backups.dados.saude.ultimo_ok_em, agora)}` : "nenhum backup concluído",
      carregando: backups.carregando,
    },
    {
      rotulo: "Componentes",
      valor: componentes.length > 0 ? `${numero(componentes.filter((componente) => componente.status === "ok").length)}/${numero(componentes.length)}` : "—",
      tom: componentes.some((componente) => componente.status === "erro") ? "erro" : componentes.some((componente) => componente.status === "atencao") ? "espera" : "ok",
      contexto: "API, fila, banco e agenda",
      carregando: painel.carregando,
    },
  ];

  const colunasBackup: Array<ColunaTabela<BackupRegistro>> = [
    { id: "quando", cabecalho: "Início", ordenavel: true, celula: (registro) => <DataHora iso={registro.iniciado_em} /> },
    { id: "tipo", cabecalho: "Tipo", celula: (registro) => <Etiqueta tom="neutro">{registro.tipo}</Etiqueta> },
    { id: "status", cabecalho: "Situação", ordenavel: true, celula: (registro) => <IndicadorEstado {...estadoDoBackup(registro.status)} titulo={registro.erro ?? registro.detalhe ?? undefined} /> },
    { id: "tamanho", cabecalho: "Tamanho", alinhamento: "direita", numerica: true, celula: (registro) => (registro.tamanho_bytes ? bytesParaTexto(registro.tamanho_bytes) : "—") },
    { id: "empresas", cabecalho: "Empresas", alinhamento: "direita", numerica: true, celula: (registro) => numero(registro.empresas) },
    { id: "documentos", cabecalho: "Documentos", alinhamento: "direita", numerica: true, celula: (registro) => numero(registro.documentos) },
    { id: "execucoes", cabecalho: "Execuções", alinhamento: "direita", numerica: true, ocultaPorPadrao: true, celula: (registro) => numero(registro.execucoes) },
    {
      id: "teste",
      cabecalho: "Restauração testada",
      celula: (registro) =>
        registro.restauracao_testada_em ? (
          <IndicadorEstado
            tom={registro.restauracao_ok ? "ok" : "erro"}
            rotulo={registro.restauracao_ok ? "Restauração ok" : "Falhou"}
            icone={registro.restauracao_ok ? "verificar-circulo" : "negar"}
            detalhe={<span className="nums">· {dataHora(registro.restauracao_testada_em)}</span>}
          />
        ) : (
          <span className="text-tinta-fraca">nunca testada</span>
        ),
    },
    {
      id: "acoes",
      cabecalho: "",
      alinhamento: "direita",
      celula: (registro) => (
        <Botao
          variante="sutil"
          tamanho="sm"
          onClick={() => testarBackup(registro)}
          carregando={executandoBackup === registro.id}
          disabled={somenteLeitura || !ehAdmin(papel)}
          title={!ehAdmin(papel) ? "Somente administrador testa restauração" : somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Testar restauração deste arquivo"}
        >
          Testar restauração
        </Botao>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Saúde"
        descricao="Componentes, disco, banco, fila e backup — o que sustenta a captura automática."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={recarregar} carregando={saude.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            <Botao
              variante="primaria"
              onClick={executarBackup}
              carregando={executandoBackup === 0}
              disabled={somenteLeitura || !ehAdmin(papel)}
              title={!ehAdmin(papel) ? "Somente administrador executa backup manual" : somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="disco" className="h-4 w-4" />}
            >
              Executar backup agora
            </Botao>
          </div>
        }
      />

      {problemas.length > 0 ? (
        <Aviso tom="erro" icone="risco" titulo={`${numero(problemas.length)} ${plural(problemas.length, "problema detectado", "problemas detectados")}`}>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-sm">
            {problemas.map((problema) => (
              <li key={problema}>{problema}</li>
            ))}
          </ul>
        </Aviso>
      ) : null}

      {backups.dados?.saude.atrasado ? (
        <Aviso tom="erro" icone="disco" titulo="Backup atrasado">
          O último backup concluído foi {backups.dados.saude.ultimo_ok_em ? tempoRelativo(backups.dados.saude.ultimo_ok_em, agora) : "nunca registrado"}. Sem
          backup recente, uma falha de disco perde o acervo inteiro. Execute um backup agora e verifique o agendador.
        </Aviso>
      ) : null}

      <GradeKpis itens={indicadores} colunas={5} rotulo="Estado do ambiente" />

      <div className="grid gap-4 xl:grid-cols-2">
        <Cartao titulo="Componentes" descricao="Leitura de /painel/operacional">
          {painel.carregando ? (
            <EsqueletoBloco linhas={4} />
          ) : painel.erro ? (
            <EstadoErro erro={painel.erro} aoTentarNovamente={painel.atualizar} contexto="carregar os componentes" />
          ) : componentes.length === 0 ? (
            <EstadoVazio inline titulo="Nenhum componente reportado" icone="saude" />
          ) : (
            <ul className="divide-y divide-traco">
              {componentes.map((componente) => {
                const estado = estadoDoComponente(componente.status);
                return (
                  <li key={componente.nome} className="flex items-start justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-tinta">{componente.nome}</p>
                      <p className="truncate text-xs text-tinta-suave" title={componente.detalhe}>
                        {componente.detalhe}
                      </p>
                    </div>
                    <IndicadorEstado {...estado} variante="etiqueta" className="flex-none" />
                  </li>
                );
              })}
            </ul>
          )}
        </Cartao>

        <Cartao titulo="Ambiente" descricao="Como esta instalação está configurada">
          {sistema.carregando ? (
            <EsqueletoBloco linhas={5} />
          ) : sistema.erro ? (
            <EstadoErro erro={sistema.erro} aoTentarNovamente={sistema.atualizar} contexto="carregar as informações do sistema" />
          ) : sistema.dados ? (
            <div className="space-y-4">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <Dado rotulo="Modo" valor={sistema.dados.modo === "docker" ? "Docker" : sistema.dados.modo} />
                <Dado rotulo="Banco" valor={sistema.dados.banco} mono />
                <Dado rotulo="Pasta de dados" valor={sistema.dados.dados_dir} mono />
                <Dado rotulo="Fila" valor={sistema.dados.fila.modo} mono />
                <Dado rotulo="Hora do servidor" valor={dataHora(sistema.dados.hora_do_servidor)} />
                <Dado
                  rotulo="Webhook"
                  valor={
                    sistema.dados.webhook?.configurado
                      ? `nível mínimo ${sistema.dados.webhook.nivel_minimo} · a cada ${numero(sistema.dados.webhook.intervalo_minutos)} min`
                      : "não configurado"
                  }
                  tom={sistema.dados.webhook?.configurado ? undefined : "espera"}
                />
              </dl>

              <div>
                <p className="mb-1.5 text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">Agenda da fila</p>
                {Object.keys(sistema.dados.fila.agenda).length === 0 ? (
                  <p className="text-sm text-tinta-fraca">Nenhuma tarefa agendada.</p>
                ) : (
                  <ul className="divide-y divide-traco rounded-controle border border-traco">
                    {Object.entries(sistema.dados.fila.agenda).map(([chave, item]) => (
                      <li key={chave} className="flex items-baseline justify-between gap-3 px-3 py-2 text-sm">
                        <span className="min-w-0 truncate text-tinta">{chave}</span>
                        <span className="nums flex-none text-xs text-tinta-suave">{item.tarefa ?? "—"}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : null}
        </Cartao>
      </div>

      <Cartao
        titulo="Backups"
        descricao="Histórico, tamanho e teste de restauração — backup não testado é esperança, não cópia"
        acoes={
          backups.dados ? (
            <span className="nums text-xs text-tinta-suave">
              retenção {numero(backups.dados.saude.retencao)} · {bytesParaTexto(backups.dados.saude.tamanho_total_bytes)} ocupados ·{" "}
              {numero(backups.dados.saude.erros_recentes)} erros recentes
            </span>
          ) : undefined
        }
      >
        {backups.dados ? (
          <div className="mb-4 space-y-3">
            <BarraProgresso
              rotulo="Tempo desde o último backup concluído"
              valor={Math.min(backups.dados.saude.horas_desde_ultimo_ok ?? 0, 48)}
              maximo={48}
              tom={backups.dados.saude.atrasado ? "erro" : (backups.dados.saude.horas_desde_ultimo_ok ?? 0) > 26 ? "espera" : "ok"}
              descricao={
                backups.dados.saude.ultimo_ok_em
                  ? `Último backup ok ${tempoRelativo(backups.dados.saude.ultimo_ok_em, agora)} (${bytesParaTexto(backups.dados.saude.ultimo_ok_tamanho_bytes ?? 0)}) · próximo previsto ${
                      backups.dados.saude.proximo_previsto_em ? dataHora(backups.dados.saude.proximo_previsto_em) : "—"
                    }`
                  : "Nenhum backup concluído ainda"
              }
            />
            <p className="text-xs text-tinta-suave">
              Último teste de restauração:{" "}
              {backups.dados.saude.ultimo_teste_em ? (
                <span className={backups.dados.saude.ultimo_teste_ok ? "text-ok" : "text-erro"}>
                  {tempoRelativo(backups.dados.saude.ultimo_teste_em, agora)} · {backups.dados.saude.ultimo_teste_ok ? "sucesso" : "falha"}
                </span>
              ) : (
                <span className="text-espera">nunca executado</span>
              )}
            </p>
          </div>
        ) : null}

        <Tabela
          linhas={backups.dados?.registros ?? []}
          colunas={colunasBackup}
          chaveDaLinha={(registro) => registro.id}
          legenda="Registros de backup"
          estados={{
            carregando: backups.carregando,
            erro: backups.erro,
            aoTentarNovamente: backups.atualizar,
            vazioTitulo: "Nenhum backup registrado",
            vazioInstrucao: "Execute um backup agora e confira o agendador na fila (Celery beat).",
            vazioIcone: "disco",
          }}
          rodape={
            <p className="nums text-xs text-tinta-suave">
              {numero(backups.dados?.registros.length ?? 0)} {plural(backups.dados?.registros.length ?? 0, "registro", "registros")} · retenção{" "}
              {numero(backups.dados?.saude.retencao ?? 0)}
            </p>
          }
        />
      </Cartao>
    </div>
  );
}

