"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { bytesParaTexto, horaLocal } from "@/lib/competencia";
import type { EstadoAtualizacao, InfoSistema, ResumoCertificado } from "@/lib/types";

/**
 * Configurações — a tela de manutenção do programa instalado.
 *
 * No modo desktop, esta é a tela que substitui o "chamar o TI": mostra onde
 * estão os dados, se o computador está protegido (backup), se o certificado
 * está válido, se o agendador está rodando e como atualizar. São as cinco
 * perguntas que um contador faz quando algo parece estranho — todas respondidas
 * sem abrir uma pasta no Windows Explorer por conta própria.
 */
export default function ConfiguracoesPage() {
  const [info, setInfo] = useState<InfoSistema | null>(null);
  const [atualizacao, setAtualizacao] = useState<EstadoAtualizacao | null>(null);
  const [certificados, setCertificados] = useState<ResumoCertificado[]>([]);
  const [saude, setSaude] = useState<{ problemas: string[]; disco_livre_bytes: number | null } | null>(
    null
  );
  const [logs, setLogs] = useState<string[] | null>(null);
  const [aviso, setAviso] = useState<{ tom: "ok" | "erro"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    api.infoSistema().then(setInfo).catch(() => {});
    api.estadoAtualizacao().then(setAtualizacao).catch(() => {});
    api.resumoCertificados().then(setCertificados).catch(() => {});
    api.saudeDetalhada().then(setSaude).catch(() => {});
  }, []);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, 30_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  async function executar(nome: string, acao: () => Promise<string | void>) {
    setOcupado(nome);
    setAviso(null);
    try {
      const texto = await acao();
      if (texto) setAviso({ tom: "ok", texto });
    } catch (e) {
      setAviso({
        tom: "erro",
        texto: e instanceof ApiError ? e.message : "Não foi possível concluir.",
      });
    } finally {
      setOcupado(null);
      carregar();
    }
  }

  const vencidos = certificados.filter((c) => c.vencido);
  const semCertificado = certificados.filter((c) => !c.tem_certificado);
  const vencendo = certificados.filter((c) => c.vence_em_breve);

  return (
    <div className="max-w-4xl">
      <div className="mb-8">
        <p className="font-serif text-2xl text-ink">Configurações</p>
        <p className="mt-1 text-sm text-ink-muted">
          Versão, atualização, backup, certificados e onde ficam os seus dados.
        </p>
      </div>

      {aviso && (
        <p
          className={`mb-6 border-l-2 px-4 py-3 text-sm ${
            aviso.tom === "ok"
              ? "border-accent bg-accent-soft text-ink"
              : "border-danger bg-danger-soft text-danger"
          }`}
        >
          {aviso.texto}
        </p>
      )}

      {saude && saude.problemas.length > 0 && (
        <div className="mb-6 border-l-2 border-danger bg-danger-soft px-4 py-3 text-sm text-danger">
          <p className="font-medium">Atenção neste computador:</p>
          <ul className="mt-1 list-inside list-disc">
            {saude.problemas.map((problema) => (
              <li key={problema}>{problema}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ---------------------------------------------------------- versão */}
      <section className="mb-6 border border-line bg-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-base font-medium text-ink">
              Versão {atualizacao?.versao_atual ?? info?.versao ?? "—"}
            </p>
            <p className="mt-1 max-w-xl text-sm text-ink-muted">
              {atualizacao?.etapa === "disponivel" || atualizacao?.disponivel ? (
                <>
                  Versão <span className="text-ink">{atualizacao.disponivel?.versao}</span>{" "}
                  disponível
                  {atualizacao.disponivel?.tamanho
                    ? ` (${bytesParaTexto(atualizacao.disponivel.tamanho)})`
                    : ""}
                  .
                </>
              ) : atualizacao?.etapa === "verificando" ? (
                "Verificando se há versão nova…"
              ) : /* "não consegui perguntar" não é "está tudo atualizado": dizer
                    que está na versão mais recente quando a verificação falhou
                    esconde do usuário justamente a informação que ele precisa. */
              atualizacao?.mensagem.startsWith("Não foi possível") ? (
                <>
                  <span className="text-warn">{atualizacao.mensagem}</span> O programa
                  continua funcionando normalmente — ele tenta de novo sozinho mais tarde.
                </>
              ) : (
                <>
                  Você está na versão mais recente.{" "}
                  {atualizacao?.verificado_em && (
                    <>Última verificação: {horaLocal(atualizacao.verificado_em)}.</>
                  )}
                </>
              )}
            </p>
            {atualizacao?.disponivel?.notas && (
              <pre className="mt-3 max-w-xl whitespace-pre-wrap border-l-2 border-line pl-3 font-sans text-xs text-ink-muted">
                {atualizacao.disponivel.notas}
              </pre>
            )}
          </div>
          <div className="flex flex-none flex-col items-end gap-2">
            {atualizacao?.disponivel ? (
              <button
                type="button"
                disabled={ocupado !== null}
                onClick={() =>
                  executar("atualizar", async () => {
                    await api.aplicarAtualizacao();
                    return "Baixando a atualização — o programa reabre sozinho em instantes.";
                  })
                }
                className="bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                Atualizar agora
              </button>
            ) : (
              <button
                type="button"
                disabled={ocupado !== null}
                onClick={() =>
                  executar("verificar", async () => {
                    const resposta = await api.verificarAtualizacao();
                    return resposta.mensagem;
                  })
                }
                className="border border-line px-4 py-2 text-sm text-accent hover:border-accent disabled:opacity-50"
              >
                {ocupado === "verificar" ? "Verificando…" : "Verificar agora"}
              </button>
            )}
            <p className="max-w-[14rem] text-right text-xs text-ink-muted">
              {info?.atualizacao.empacotado
                ? "O programa se atualiza sozinho e mantém seus dados."
                : "Modo desenvolvimento: a atualização automática fica desligada."}
            </p>
          </div>
        </div>
        {atualizacao?.erro && (
          <p className="mt-3 text-sm text-danger">
            Última tentativa falhou: {atualizacao.erro}
          </p>
        )}
      </section>

      {/* ------------------------------------------------- começa com o PC */}
      <section className="mb-6 border border-line bg-surface p-6">
        <p className="text-base font-medium text-ink">Trabalhar sozinho</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="h-4 w-4 accent-accent"
              checked={info?.iniciar_com_windows ?? false}
              disabled={!info?.pode_iniciar_com_windows || ocupado !== null}
              onChange={(e) =>
                executar("iniciar", async () => {
                  const resposta = await api.iniciarComWindows(e.target.checked);
                  return resposta.mensagem;
                })
              }
            />
            Abrir o NotasFlow junto com o Windows
          </label>
          {!info?.pode_iniciar_com_windows && (
            <span className="text-xs text-ink-muted">
              disponível só no programa instalado no Windows
            </span>
          )}
        </div>
        <p className="mt-2 max-w-2xl text-xs text-ink-muted">
          Com esta opção ligada, o NotasFlow abre minimizado na bandeja ao ligar o computador e
          continua consultando a SEFAZ no horário certo — inclusive nos dias em que você não abrir
          o programa. O ícone fica perto do relógio; clicar nele abre esta tela.
        </p>

        {info?.fila && (
          <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-line pt-4 text-xs text-ink-muted sm:grid-cols-4">
            <span>
              fila agora{" "}
              <span className="font-mono text-ink">
                {info.fila.pendentes ?? 0} esperando · {info.fila.em_execucao?.importar_documentos ?? 0}{" "}
                varrendo
              </span>
            </span>
            <span>
              consultas simultâneas <span className="font-mono text-ink">{info.fila.concorrencia}</span>
            </span>
            {info.fila.agenda &&
              Object.entries(info.fila.agenda).map(([nome, tarefa]) => (
                <span key={nome}>
                  {nome.replace(/-/g, " ")}{" "}
                  <span className="font-mono text-ink">
                    {Math.round(tarefa.intervalo_segundos / 60)} min
                  </span>
                </span>
              ))}
          </div>
        )}
      </section>

      {/* -------------------------------------------------------- backup */}
      <section className="mb-6 border border-line bg-surface p-6">
        <p className="text-base font-medium text-ink">Backup dos seus dados</p>
        <p className="mt-1 max-w-2xl text-sm text-ink-muted">
          Um arquivo ZIP com o banco de notas, os certificados e a configuração — tudo que é preciso
          para voltar a funcionar em outro computador. Guarde em um pendrive ou na nuvem da
          contabilidade.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={ocupado !== null}
            onClick={() =>
              executar("backup", async () => {
                const resposta = await api.gerarBackup();
                return `Backup gerado: ${resposta.mensagem}`;
              })
            }
            className="bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {ocupado === "backup" ? "Gerando…" : "Gerar backup agora"}
          </button>
          <button
            type="button"
            disabled={ocupado !== null}
            onClick={() =>
              executar("abrir", async () => {
                const resposta = await api.abrirPastaDados();
                return `Abrindo ${resposta.pasta}`;
              })
            }
            className="border border-line px-4 py-2 text-sm text-accent hover:border-accent disabled:opacity-50"
          >
            Abrir a pasta de dados
          </button>
          {saude?.disco_livre_bytes != null && (
            <span className="text-xs text-ink-muted">
              espaço livre neste computador:{" "}
              <span
                className={
                  saude.disco_livre_bytes < 2 * 1024 ** 3 ? "font-mono text-danger" : "font-mono text-ink"
                }
              >
                {bytesParaTexto(saude.disco_livre_bytes)}
              </span>
              {saude.disco_livre_bytes < 2 * 1024 ** 3 && " — pouco espaço atrapalha o download de XMLs"}
            </span>
          )}
        </div>
        <p className="mt-3 text-xs text-ink-muted">
          Os últimos 10 backups ficam guardados em <span className="font-mono">backups/</span> na
          pasta de dados. Ele é gerado sozinho uma vez por dia enquanto o programa está aberto.
        </p>
      </section>

      {/* --------------------------------------------------- certificados */}
      <section className="mb-6 border border-line bg-surface p-6">
        <p className="text-base font-medium text-ink">Certificados digitais</p>
        {certificados.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">
            Nenhuma empresa cadastrada ainda.
          </p>
        ) : (
          <>
            <p className="mt-1 text-sm text-ink-muted">
              {certificados.length - semCertificado.length} de {certificados.length} empresas com
              certificado A1 instalado.
            </p>
            {(vencidos.length > 0 || vencendo.length > 0) && (
              <p className="mt-2 text-sm">
                {vencidos.length > 0 && (
                  <span className="text-danger">
                    vencido: {vencidos.map((c) => c.razao_social).join(", ")}
                  </span>
                )}
                {vencidos.length > 0 && vencendo.length > 0 && " · "}
                {vencendo.length > 0 && (
                  <span className="text-warn">
                    vence em até 30 dias:{" "}
                    {vencendo.map((c) => `${c.razao_social} (${c.dias_para_vencer}d)`).join(", ")}
                  </span>
                )}
              </p>
            )}
            <table className="mt-4 w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-ink-muted">
                  <th className="py-2 font-normal">Empresa</th>
                  <th className="py-2 font-normal">Validade</th>
                  <th className="py-2 text-right font-normal">Situação</th>
                </tr>
              </thead>
              <tbody>
                {certificados.map((certificado) => (
                  <tr key={certificado.empresa_id} className="border-b border-line last:border-0">
                    <td className="py-2 text-ink">{certificado.razao_social}</td>
                    <td className="py-2 font-mono text-xs text-ink-muted">
                      {certificado.validade
                        ? certificado.validade.split("-").reverse().join("/")
                        : "—"}
                    </td>
                    <td className="py-2 text-right">
                      {!certificado.tem_certificado ? (
                        <span className="text-ink-muted">sem certificado</span>
                      ) : certificado.vencido ? (
                        <span className="text-danger">vencido — renovar</span>
                      ) : certificado.vence_em_breve ? (
                        <span className="text-warn">
                          vence em {certificado.dias_para_vencer} dias
                        </span>
                      ) : (
                        <span className="text-accent">
                          válido por {certificado.dias_para_vencer} dias
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      {/* ----------------------------------------------------------- logs */}
      <section className="mb-6 border border-line bg-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-base font-medium text-ink">Registro de atividade</p>
            <p className="mt-1 text-xs text-ink-muted">
              As últimas linhas do que o programa fez. É isto que você envia para quem te dá
              suporte quando algo não funciona.
            </p>
          </div>
          <button
            type="button"
            disabled={ocupado !== null}
            onClick={() =>
              executar("logs", async () => {
                const resposta = await api.lerLogs(300);
                setLogs(resposta.linhas);
                return resposta.arquivo ? `Lendo ${resposta.arquivo}` : "Sem registros ainda.";
              })
            }
            className="border border-line px-4 py-2 text-sm text-accent hover:border-accent disabled:opacity-50"
          >
            {logs ? "Atualizar registros" : "Ver registros"}
          </button>
        </div>
        {logs && (
          <pre className="mt-4 max-h-80 overflow-auto border border-line bg-bg p-3 font-mono text-[11px] leading-relaxed text-ink">
            {logs.length ? logs.join("\n") : "Nada registrado ainda."}
          </pre>
        )}
      </section>

      {/* ------------------------------------------------------- sistema */}
      {info && (
        <section className="border border-line bg-surface p-6">
          <p className="text-base font-medium text-ink">Sobre este computador</p>
          <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2 text-xs sm:grid-cols-2">
            {[
              ["Programa", info.empacotado ? "instalado" : "em desenvolvimento"],
              ["Banco de dados", info.banco === "sqlite" ? "local (arquivo único)" : "PostgreSQL"],
              ["Modo", info.modo_desktop ? "programa no computador" : "servidor"],
              ["Pasta do programa", info.pasta_programa],
              ["Pasta dos dados", info.pasta_dados],
              ["Pasta dos registros", info.pasta_logs],
              ["Painel web", info.painel_web_presente ? "presente" : "ausente"],
            ].map(([rotulo, valor]) => (
              <div key={rotulo} className="flex justify-between gap-4 border-b border-line py-1.5">
                <dt className="text-ink-muted">{rotulo}</dt>
                <dd className="truncate font-mono text-ink" title={String(valor)}>
                  {valor}
                </dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 flex flex-wrap gap-3">
            <a
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent hover:underline"
            >
              documentação técnica da API
            </a>
            <button
              type="button"
              disabled={ocupado !== null}
              onClick={() =>
                executar("encerrar", async () => {
                  await api.encerrarPrograma();
                  window.close();
                  return "Encerrando o NotasFlow. Pode fechar esta janela.";
                })
              }
              className="text-xs text-ink-muted hover:text-danger"
            >
              encerrar o programa
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
