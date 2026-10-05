"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { dataCurta, numero, plural } from "@/lib/format";
import { useRecurso } from "@/lib/useRecurso";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { DataHora, Truncado } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import type { AchadoPrevoo, LinhaPrevoo } from "@/lib/types";
import type { Tom } from "@/lib/estados";

type Situacao = LinhaPrevoo["situacao"];

/**
 * Como cada situação se apresenta. `dispensado` é deliberadamente neutro e
 * não conta como problema: "já tem autorização ativa, não há nada a fazer" é
 * um bom desfecho, e pintá-lo de vermelho faria o operador perseguir um
 * cliente que já está resolvido.
 */
const APARENCIA: Record<Situacao, { tom: Tom; rotulo: string; icone: "verificar-circulo" | "alerta" | "negar" | "info" }> = {
  apto: { tom: "ok", rotulo: "Apto", icone: "verificar-circulo" },
  atencao: { tom: "espera", rotulo: "Atenção", icone: "alerta" },
  bloqueado: { tom: "erro", rotulo: "Bloqueado", icone: "negar" },
  dispensado: { tom: "neutro", rotulo: "Dispensado", icone: "info" },
};

const ORDEM: Situacao[] = ["bloqueado", "atencao", "apto", "dispensado"];

function Achados({ achados }: { achados: AchadoPrevoo[] }) {
  if (achados.length === 0) {
    return <span className="text-xs text-tinta-fraca">—</span>;
  }
  return (
    <ul className="min-w-0 space-y-0.5">
      {achados.map((achado) => (
        <li key={achado.codigo} className="min-w-0">
          <Truncado texto={achado.mensagem} titulo={`${achado.mensagem}\n→ ${achado.acao}`} className="text-xs text-tinta" />
        </li>
      ))}
    </ul>
  );
}

/**
 * Pré-voo do lote.
 *
 * Responde uma pergunta antes de qualquer navegador abrir: **quais clientes
 * dá para tocar hoje, e o que falta para os outros?** Descobrir no cliente 12
 * de 15 que o certificado venceu custa uma sessão inteira de retrabalho;
 * descobrir aqui custa trinta segundos.
 *
 * A tela é somente leitura por construção — o endpoint não cria job, não
 * altera autorização e pode ser recarregado à vontade.
 */
export function PreVoo() {
  const [somentePendentes, setSomentePendentes] = useState(true);
  const [baixando, setBaixando] = useState(false);
  const { avisar } = useToast();
  const prevoo = useRecurso(() => api.preVooProcuracoes(), []);
  const metricas = useRecurso(() => api.metricasProcuracoes(30), []);

  async function baixarCsv() {
    setBaixando(true);
    try {
      await api.baixarRelatorioProcuracoes({ somentePendentes });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível baixar o CSV", descricao: mensagemDoErro(falha) });
    } finally {
      setBaixando(false);
    }
  }

  const colunas = useMemo<Array<ColunaTabela<LinhaPrevoo>>>(
    () => [
      {
        id: "empresa",
        cabecalho: "Cliente",
        largura: "min-w-56",
        fixa: true,
        celula: (linha) => (
          <Link href={`/dashboard/procuracoes/empresa?id=${linha.empresa_id}`} className="min-w-0 hover:underline">
            <p className="truncate font-medium text-tinta">{linha.razao_social}</p>
            <p className="truncate font-mono text-2xs text-tinta-fraca">{linha.documento}</p>
          </Link>
        ),
      },
      {
        id: "situacao",
        cabecalho: "Pré-voo",
        largura: "w-36",
        celula: (linha) => <IndicadorEstado {...APARENCIA[linha.situacao]} />,
      },
      {
        id: "achados",
        cabecalho: "O que falta",
        largura: "min-w-72",
        celula: (linha) => <Achados achados={linha.achados} />,
      },
      {
        id: "certificado",
        cabecalho: "Certificado A1",
        largura: "min-w-40",
        celula: (linha) =>
          linha.certificado ? (
            <div className="min-w-0">
              <Truncado texto={linha.certificado} className="text-xs text-tinta" />
              {linha.certificado_valido_ate ? (
                <p className="text-2xs text-tinta-fraca">até {dataCurta(linha.certificado_valido_ate)}</p>
              ) : null}
            </div>
          ) : (
            <span className="text-xs text-tinta-fraca">não encontrado</span>
          ),
      },
      {
        id: "vigencia",
        cabecalho: "Vigência prevista",
        dica: "5 anos a partir da outorga — o máximo legal da IN RFB nº 2.320/2026",
        largura: "w-40",
        celula: (linha) =>
          linha.vigencia_prevista ? (
            <span className="nums">{dataCurta(linha.vigencia_prevista)}</span>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
    ],
    []
  );

  const dados = prevoo.dados;
  const linhas = useMemo(() => {
    const todas = dados?.linhas ?? [];
    const visiveis = somentePendentes ? todas.filter((linha) => linha.situacao !== "dispensado") : todas;
    return [...visiveis].sort((a, b) => ORDEM.indexOf(a.situacao) - ORDEM.indexOf(b.situacao));
  }, [dados, somentePendentes]);

  const contagem = dados?.contagem ?? {};
  const kpis: KpiProps[] = [
    {
      rotulo: "Aptos agora",
      valor: numero(contagem.apto ?? 0),
      tom: "ok",
      contexto: "podem ser iniciados sem pendência",
      carregando: prevoo.carregando,
    },
    {
      rotulo: "Com atenção",
      valor: numero(contagem.atencao ?? 0),
      tom: "espera",
      contexto: "revise a ressalva antes de agir",
      carregando: prevoo.carregando,
    },
    {
      rotulo: "Bloqueados",
      valor: numero(contagem.bloqueado ?? 0),
      tom: "erro",
      contexto: "resolver antes de abrir o portal",
      carregando: prevoo.carregando,
    },
    {
      rotulo: "Dispensados",
      valor: numero(contagem.dispensado ?? 0),
      tom: "neutro",
      contexto: "já autorizados — nada a fazer",
      carregando: prevoo.carregando,
    },
  ];

  const porCodigo = Object.entries(dados?.por_codigo ?? {}).sort((a, b) => b[1] - a[1]);
  const tempoEtapa = Object.entries(metricas.dados?.tempo_por_etapa ?? {}).sort((a, b) => b[1] - a[1]);
  const carteiraVazia = (dados?.linhas.length ?? 0) === 0;
  let vazioTitulo = "Nenhum cliente na carteira";
  let vazioInstrucao = "Cadastre empresas para que o pré-voo tenha o que avaliar.";
  if (dados?.bloqueio_de_ambiente) {
    vazioTitulo = "Carteira não avaliada";
    vazioInstrucao = "Resolva os bloqueios de ambiente acima e reavalie para conferir a carteira.";
  } else if (!carteiraVazia && somentePendentes) {
    vazioTitulo = "Nenhuma pendência";
    vazioInstrucao = "Todos os clientes avaliados já têm autorização ativa.";
  }

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        kicker="Procurações RFB"
        titulo="Pré-voo do lote"
        descricao="Checagem completa antes do primeiro navegador abrir: ambiente, estação, Assinador, certificado de cada cliente e prazos. Nada aqui altera dado nenhum — pode recarregar à vontade."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao
              variante="sutil"
              onClick={() => {
                prevoo.atualizar();
                metricas.atualizar();
              }}
              carregando={prevoo.atualizando}
              iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
            >
              Reavaliar
            </Botao>
            <Botao
              variante="sutil"
              carregando={baixando}
              onClick={baixarCsv}
              title="Planilha da carteira (separador ';', abre direto no Excel em português)"
              iconeEsquerda={<Icone nome="baixar" className="h-4 w-4" />}
            >
              Baixar CSV
            </Botao>
          </div>
        }
      />

      {dados?.bloqueio_de_ambiente ? (
        <Aviso tom="erro" icone="negar" titulo="O ambiente ainda não está pronto" urgente>
          <ul className="mt-1 space-y-1 text-xs">
            {dados.ambiente.map((achado) => (
              <li key={achado.codigo}>
                <span className="font-medium">{achado.mensagem}</span> — {achado.acao}
              </li>
            ))}
          </ul>
        </Aviso>
      ) : (dados?.ambiente ?? []).length > 0 ? (
        <Aviso tom="espera" icone="alerta" titulo="Dá para começar, mas repare nisto">
          <ul className="mt-1 space-y-1 text-xs">
            {(dados?.ambiente ?? []).map((achado) => (
              <li key={achado.codigo}>
                <span className="font-medium">{achado.mensagem}</span> — {achado.acao}
              </li>
            ))}
          </ul>
        </Aviso>
      ) : null}

      <GradeKpis itens={kpis} />

      {porCodigo.length > 0 ? (
        <section className="rounded-xl border border-borda bg-superficie p-4">
          <h2 className="text-sm font-semibold text-tinta-forte">Pendências por motivo</h2>
          <p className="mt-0.5 text-xs text-tinta-suave">
            Resolver de cima para baixo costuma ser mais rápido: o mesmo motivo quase sempre tem a mesma causa.
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {porCodigo.map(([codigo, quantidade]) => (
              <li key={codigo} className="rounded-lg border border-borda px-2.5 py-1 text-xs text-tinta">
                <span className="font-mono text-2xs text-tinta-suave">{codigo}</span>{" "}
                <span className="nums font-semibold">{numero(quantidade)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <Tabela
        linhas={linhas}
        colunas={colunas}
        chaveDaLinha={(linha) => linha.empresa_id}
        legenda="Situação de pré-voo de cada cliente da carteira"
        estados={{
          carregando: prevoo.carregando,
          erro: prevoo.erro,
          aoTentarNovamente: prevoo.atualizar,
          vazioTitulo,
          vazioInstrucao,
          vazioIcone: "verificar-circulo",
        }}
        ferramentas={
          <label className="flex items-center gap-2 text-xs text-tinta-suave">
            <input
              type="checkbox"
              checked={somentePendentes}
              onChange={(evento) => setSomentePendentes(evento.target.checked)}
              className="h-3.5 w-3.5 rounded border-borda"
            />
            Ocultar quem já está autorizado
          </label>
        }
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {numero(linhas.length)} {plural(linhas.length, "cliente", "clientes")} em tela ·{" "}
            {dados?.gerado_em ? (
              <>
                avaliado em <DataHora iso={dados.gerado_em} />
              </>
            ) : null}
          </p>
        }
      />

      {metricas.dados && metricas.dados.jobs_considerados > 0 ? (
        <section className="rounded-xl border border-borda bg-superficie p-4">
          <h2 className="text-sm font-semibold text-tinta-forte">Onde o tempo foi gasto (últimos 30 dias)</h2>
          <p className="mt-0.5 text-xs text-tinta-suave">
            Reconstruído do histórico de eventos dos jobs. A espera humana é contada à parte: ela domina o relógio e não é
            defeito do sistema — é o portal, o cliente e o aceite.
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <dt className="text-2xs uppercase tracking-wide text-tinta-fraca">Concluídos</dt>
              <dd className="nums text-sm font-semibold text-tinta-forte">
                {numero(metricas.dados.concluidos)} de {numero(metricas.dados.jobs_considerados)}
              </dd>
            </div>
            <div>
              <dt className="text-2xs uppercase tracking-wide text-tinta-fraca">Duração média</dt>
              <dd className="nums text-sm font-semibold text-tinta-forte">{numero(metricas.dados.duracao_media_minutos)} min</dd>
            </div>
            <div>
              <dt className="text-2xs uppercase tracking-wide text-tinta-fraca">Espera humana</dt>
              <dd className="nums text-sm font-semibold text-tinta-forte">
                {numero(metricas.dados.espera_humana_media_minutos)} min
              </dd>
            </div>
            <div>
              <dt className="text-2xs uppercase tracking-wide text-tinta-fraca">Intervenções</dt>
              <dd className="nums text-sm font-semibold text-tinta-forte">{numero(metricas.dados.intervencoes_humanas)}</dd>
            </div>
          </dl>
          {tempoEtapa.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {tempoEtapa.slice(0, 6).map(([etapa, minutos]) => (
                <li key={etapa} className="flex items-baseline justify-between gap-3 text-xs">
                  <span className="truncate text-tinta">{etapa}</span>
                  <span className="nums flex-none text-tinta-suave">{numero(minutos)} min</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
