"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { numero, plural } from "@/lib/format";
import { estadoDaEstacao } from "@/lib/estados";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useRecurso } from "@/lib/useRecurso";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Entrada } from "@/components/ui/Campo";
import { CopiavelMono } from "@/components/ui/CopiavelMono";
import { DataHora, Truncado } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Modal } from "@/components/ui/Modal";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import type { AgenteProcuracao, CredencialAgente } from "@/lib/types";

/**
 * Gestão das estações (Cajuru Agent).
 *
 * Uma estação é a máquina Windows que tem os certificados A1 e o Assinador
 * SERPRO. O servidor nunca vê a chave privada: ele emite uma ordem de trabalho
 * e a estação a executa junto do operador.
 *
 * O segredo de matrícula aparece **uma única vez**, no momento em que é
 * gerado. Não há tela, log ou endpoint que o recupere depois — se for perdido,
 * gera-se outro, e o anterior deixa de valer no mesmo instante.
 */
export function Estacoes() {
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();

  const [matriculaAberta, setMatriculaAberta] = useState(false);
  const [nome, setNome] = useState("");
  const [credencial, setCredencial] = useState<CredencialAgente | null>(null);
  const [processando, setProcessando] = useState(false);

  const agentes = useRecurso(() => api.agentesProcuracao(), []);
  const requisitos = useRecurso(() => api.requisitosAgente(), []);

  async function matricular() {
    setProcessando(true);
    try {
      const nova = await api.matricularAgente(nome.trim() || "Estação");
      setCredencial(nova);
      setNome("");
      agentes.atualizar();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Não foi possível matricular", descricao: mensagemDoErro(erro) });
    } finally {
      setProcessando(false);
    }
  }

  async function revogar(agente: AgenteProcuracao) {
    setProcessando(true);
    try {
      await api.revogarAgente(agente.id, "Revogada pelo administrador.");
      avisar({
        tom: "ok",
        titulo: `${agente.nome} revogada`,
        descricao: "A sessão foi encerrada e os jobs em andamento voltaram para a fila.",
      });
      agentes.atualizar();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Não foi possível revogar", descricao: mensagemDoErro(erro) });
    } finally {
      setProcessando(false);
    }
  }

  const colunas = useMemo<Array<ColunaTabela<AgenteProcuracao>>>(
    () => [
      {
        id: "nome",
        cabecalho: "Estação",
        largura: "min-w-48",
        fixa: true,
        celula: (linha) => (
          <div className="min-w-0">
            <p className="truncate font-medium text-tinta">{linha.nome}</p>
            <p className="truncate font-mono text-2xs text-tinta-fraca">{linha.identificador.slice(0, 16)}…</p>
          </div>
        ),
      },
      { id: "situacao", cabecalho: "Situação", celula: (linha) => <IndicadorEstado {...estadoDaEstacao(linha.situacao)} /> },
      {
        id: "assinador",
        cabecalho: "Assinador SERPRO",
        largura: "min-w-48",
        celula: (linha) =>
          linha.assinador_ok ? (
            <IndicadorEstado tom="ok" rotulo={`Apto ${linha.versao_assinador ?? ""}`.trim()} icone="verificar-circulo" />
          ) : (
            <div className="min-w-0">
              <IndicadorEstado tom="erro" rotulo="Não apto" icone="negar" />
              {linha.assinador_detalhe ? (
                <Truncado texto={linha.assinador_detalhe} className="mt-0.5 text-2xs text-tinta-suave" titulo={linha.assinador_detalhe} />
              ) : null}
            </div>
          ),
      },
      {
        id: "certificados",
        cabecalho: "Certificados",
        alinhamento: "direita",
        numerica: true,
        celula: (linha) => <span className="nums">{numero(linha.certificados)}</span>,
      },
      {
        id: "jobs",
        cabecalho: "Em andamento",
        alinhamento: "direita",
        numerica: true,
        celula: (linha) => <span className="nums">{numero(linha.jobs_em_andamento)}</span>,
      },
      {
        id: "heartbeat",
        cabecalho: "Último sinal",
        celula: (linha) =>
          linha.ultimo_heartbeat_em ? <DataHora iso={linha.ultimo_heartbeat_em} /> : <span className="text-tinta-fraca">nunca</span>,
      },
      {
        id: "versao",
        cabecalho: "Versão do Agent",
        ocultaPorPadrao: true,
        celula: (linha) => <span className="font-mono text-xs">{linha.versao_agente ?? "—"}</span>,
      },
      {
        id: "acoes",
        cabecalho: "",
        alinhamento: "direita",
        celula: (linha) =>
          linha.ativo ? (
            <Botao
              variante="perigo-sutil"
              tamanho="sm"
              disabled={somenteLeitura || processando}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Encerra a sessão e invalida a credencial desta máquina"}
              onClick={() => revogar(linha)}
            >
              Revogar
            </Botao>
          ) : (
            <span className="text-xs text-tinta-fraca">revogada</span>
          ),
      },
    ],
    // `revogar` é estável o bastante para o escopo desta tela.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [processando, somenteLeitura]
  );

  const lista = agentes.dados ?? [];
  const semAssinador = lista.filter((item) => item.ativo && !item.assinador_ok);

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Estações"
        descricao="Máquinas do escritório que guardam os certificados A1 e conduzem a operação no portal oficial."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={agentes.atualizar} carregando={agentes.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            <Botao
              variante="primaria"
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              onClick={() => setMatriculaAberta(true)}
              iconeEsquerda={<Icone nome="monitor" className="h-4 w-4" />}
            >
              Matricular estação
            </Botao>
          </div>
        }
      />

      <Aviso tom="info" icone="cadeado" titulo="O certificado nunca sai da máquina">
        A estação envia apenas metadados públicos do certificado (titular, CNPJ, validade, thumbprint). A chave privada e a senha permanecem sob o
        cofre do Windows, e a assinatura é feita pelo Assinador Digital SERPRO — o componente oficial que o portal da Receita aciona.
      </Aviso>

      {semAssinador.length > 0 ? (
        <Aviso
          tom="erro"
          icone="certificado"
          titulo={`${numero(semAssinador.length)} ${plural(semAssinador.length, "estação está", "estações estão")} sem Assinador apto`}
        >
          Enquanto o diagnóstico não passar, nenhum job é entregue a essas máquinas — o processo pararia no meio, com o portal aberto.
          {requisitos.dados ? (
            <ol className="mt-2 space-y-1 text-xs">
              {requisitos.dados.passos.slice(0, 4).map((passo) => (
                <li key={passo.chave}>
                  <span className="font-medium">{passo.titulo}:</span> {passo.acao}
                </li>
              ))}
            </ol>
          ) : null}
        </Aviso>
      ) : null}

      <Tabela
        linhas={lista}
        colunas={colunas}
        chaveDaLinha={(linha) => linha.id}
        legenda="Estações do módulo Procurações RFB"
        estados={{
          carregando: agentes.carregando,
          erro: agentes.erro,
          aoTentarNovamente: agentes.atualizar,
          vazioTitulo: "Nenhuma estação matriculada",
          vazioInstrucao: "Matricule a máquina que tem os certificados A1 e rode instalar_agent.ps1 nela.",
          vazioIcone: "monitor",
        }}
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {numero(lista.length)} {plural(lista.length, "estação", "estações")} ·{" "}
            {numero(lista.filter((item) => item.situacao === "online").length)} online
          </p>
        }
      />

      <Modal
        aberto={matriculaAberta}
        aoFechar={() => {
          setMatriculaAberta(false);
          setCredencial(null);
        }}
        titulo={credencial ? "Credencial gerada" : "Matricular estação"}
        descricao={
          credencial
            ? "Copie agora. Este segredo não será exibido novamente — nem por administrador, nem no log."
            : "Dê um nome que identifique a máquina física (ex.: 'PC Fiscal 01')."
        }
        rodape={
          credencial ? (
            <Botao
              variante="primaria"
              onClick={() => {
                setCredencial(null);
                setMatriculaAberta(false);
              }}
            >
              Já copiei
            </Botao>
          ) : (
            <div className="flex items-center justify-end gap-2">
              <Botao variante="sutil" onClick={() => setMatriculaAberta(false)}>
                Cancelar
              </Botao>
              <Botao variante="primaria" carregando={processando} disabled={!nome.trim()} onClick={matricular}>
                Gerar credencial
              </Botao>
            </div>
          )
        }
      >
        {credencial ? (
          <div className="space-y-3">
            <Aviso tom="espera" icone="chave" titulo="Segredo de uso único">
              {credencial.aviso}
            </Aviso>
            <div className="space-y-2">
              <div>
                <p className="text-2xs uppercase tracking-[.04em] text-tinta-fraca">Identificador</p>
                <CopiavelMono valor={credencial.agente.identificador} rotulo="Copiar identificador da estação" quebrar />
              </div>
              <div>
                <p className="text-2xs uppercase tracking-[.04em] text-tinta-fraca">Segredo</p>
                <CopiavelMono valor={credencial.segredo} rotulo="Copiar segredo da estação" quebrar />
              </div>
            </div>
            <div className="rounded-controle border border-borda-controle bg-superficie-suave p-3">
              <p className="text-2xs uppercase tracking-[.04em] text-tinta-fraca">Na máquina do escritório</p>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-2xs leading-5 text-tinta-suave">
{`.\\instalar_agent.ps1 \`
  -ServidorUrl "${typeof window !== "undefined" ? window.location.origin : "https://cajuru.seudominio.com.br"}" \`
  -Identificador "${credencial.agente.identificador}" \`
  -Segredo "<cole o segredo>"`}
              </pre>
            </div>
          </div>
        ) : (
          <Entrada
            rotulo="Nome da estação"
            value={nome}
            onChange={(evento) => setNome(evento.target.value)}
            placeholder="PC Fiscal 01"
            descricao="Use o nome pelo qual a equipe chama a máquina — é o que aparece nos alertas."
          />
        )}
      </Modal>
    </div>
  );
}
