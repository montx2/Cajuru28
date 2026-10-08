"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { contagem, contagemRegressiva, numero } from "@/lib/format";
import { estadoDaSincronizacao, type EstadoVisual } from "@/lib/estados";
import { avisoDoDisparo } from "@/lib/importacao";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { paraFiltro, rotuloPeriodo } from "@/lib/periodo";
import { rotuloProximaVarredura } from "@/lib/sincronismo";
import { usePeriodoUrl } from "@/lib/usePeriodoUrl";
import { usePolling } from "@/lib/usePolling";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useContagemAlertas } from "@/components/shell/ProvedorAlertas";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { ResumoNSU } from "@/components/fiscal/MedidorNSU";
import { ModalImportarXmls } from "./ImportarXmls";
import { ResumoImportacao } from "@/components/fiscal/ResumoImportacao";
import { SeletorEmpresas } from "@/components/fiscal/SeletorEmpresas";
import { SeletorPeriodo } from "@/components/fiscal/SeletorPeriodo";
import { Aviso } from "@/components/ui/Aviso";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Alternador, Caixa, Selecao } from "@/components/ui/Campo";
import { Dado } from "@/components/ui/Dado";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { DataHora } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { MenuSuspenso } from "@/components/ui/MenuSuspenso";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import {
  ROTULO_TIPO,
  TIPOS,
  type EstadoSincronizacao,
  type ResultadoImportacaoSelecionada,
  type TipoDocumentoFiscal,
} from "@/lib/types";


/**
 * Disparo de captura — a tela que gasta cota da SEFAZ.
 *
 * Por isso o padrão é **seleção**: "todas as empresas" era o comportamento que
 * queimava a janela de 1 hora varrendo CNPJ que ninguém pediu. A prévia existe
 * para mostrar o que vai acontecer antes de acontecer, e o disparo passa por
 * confirmação com o impacto escrito em número de empresas, tipos e período.
 */
export function Importacoes() {
  const { definir, ler, lerBooleano } = useUrlEstado();
  const { periodo, aoMudar: aoMudarPeriodo, pronto } = usePeriodoUrl();
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const { atualizar: atualizarAlertas } = useContagemAlertas();
  const agora = useAgora();
  const topo = useRef<HTMLDivElement | null>(null);

  const selecionadas = useMemo(() => {
    const bruto = ler("empresa_ids") || ler("empresa_id");
    const ids = bruto
      .split(",")
      .map((valor) => Number(valor.trim()))
      .filter((valor) => Number.isFinite(valor) && valor > 0);
    return new Set(ids);
  }, [ler]);

  const tipos = useMemo(() => {
    const bruto = ler("tipos") || ler("tipo");
    if (!bruto) return new Set<TipoDocumentoFiscal>(TIPOS);
    const escolhidos = bruto
      .split(",")
      .map((valor) => valor.trim())
      .filter((valor): valor is TipoDocumentoFiscal => TIPOS.includes(valor as TipoDocumentoFiscal));
    return new Set<TipoDocumentoFiscal>(escolhidos);
  }, [ler]);

  const forcar = lerBooleano("forcar");

  const [resultado, setResultado] = useState<{ modo: "previa" | "resultado"; dados: ResultadoImportacaoSelecionada } | null>(null);
  const [enviando, setEnviando] = useState<"previa" | "disparo" | null>(null);
  const [erroAcao, setErroAcao] = useState<string | null>(null);
  const [confirmando, setConfirmando] = useState(false);
  const [importacaoXmlAberta, setImportacaoXmlAberta] = useState(false);

  const empresas = useRecurso(() => api.listarEmpresas(), []);
  const estados = useRecurso(() => api.estadoSincronizacao(), []);
  const resumoSync = useRecurso(() => api.resumoSincronizacao(), []);
  const certificados = useRecurso(() => api.resumoCertificados(), []);

  useSinalizarAtualizacao(estados.atualizando || resumoSync.atualizando);
  // Janelas e bloqueios mudam sozinhos: 60 s mantém a tela honesta sem martelar.
  usePolling(() => {
    estados.atualizar();
    resumoSync.atualizar();
  }, 60_000);

  // Prévia/resultado de um disparo anterior não sobrevive a mudança de filtro.
  const chaveDisparo = `${Array.from(selecionadas).sort((a, b) => a - b).join(",")}|${Array.from(tipos).join(",")}|${periodo.inicio}|${periodo.fim}|${forcar}`;
  useEffect(() => {
    setResultado(null);
    setErroAcao(null);
  }, [chaveDisparo]);

  const bloqueios = useMemo(() => {
    const mapa = new Map<number, string>();
    const comLotesRecebidos = new Set((estados.dados ?? []).filter((estado) => (estado.lotes_pendentes ?? 0) > 0).map((estado) => estado.empresa_id));
    for (const certificado of certificados.dados ?? []) {
      // Reprocessar resposta já recebida é operação local, não exige A1.
      if (comLotesRecebidos.has(certificado.empresa_id)) continue;
      if (!certificado.tem_certificado) mapa.set(certificado.empresa_id, "Sem certificado A1 cadastrado");
      else if (certificado.vencido) mapa.set(certificado.empresa_id, `Certificado vencido em ${certificado.validade}`);
    }
    return mapa;
  }, [certificados.dados, estados.dados]);

  const situacoes = useMemo(() => {
    const mapa = new Map<number, EstadoVisual>();
    const prioridade: Record<string, number> = { erro: 0, espera: 1, info: 2, neutro: 3, acento: 4, ok: 5 };
    for (const estado of estados.dados ?? []) {
      const visual = estadoDaSincronizacao(estado, agora);
      const atual = mapa.get(estado.empresa_id);
      if (!atual || (prioridade[visual.tom] ?? 9) < (prioridade[atual.tom] ?? 9)) mapa.set(estado.empresa_id, visual);
    }
    return mapa;
  }, [agora, estados.dados]);

  const desabilitadas = useMemo(
    () => new Set(Array.from(bloqueios.keys()).filter((id) => bloqueios.get(id)?.startsWith("Sem certificado") || bloqueios.get(id)?.startsWith("Certificado vencido"))),
    [bloqueios]
  );

  const linhasSincronismo = useMemo(() => {
    const empresaFiltro = ler("sinc_empresa");
    const situacaoFiltro = ler("sinc_situacao");
    return (estados.dados ?? []).filter((estado) => {
      if (empresaFiltro && String(estado.empresa_id) !== empresaFiltro) return false;
      if (situacaoFiltro === "pendencia" && estado.pendencia <= 0) return false;
      if (situacaoFiltro === "bloqueada" && !estado.bloqueado_ate) return false;
      if (situacaoFiltro === "em_dia" && !estado.em_dia) return false;
      if (situacaoFiltro === "risco" && !estado.risco_documento_fora_da_distribuicao) return false;
      if (situacaoFiltro === "manual" && estado.sincronizar_automaticamente) return false;
      return true;
    });
  }, [estados.dados, ler]);

  const colunas = useMemo<Array<ColunaTabela<EstadoSincronizacao>>>(
    () => [
      {
        id: "empresa",
        cabecalho: "Empresa",
        largura: "min-w-52",
        fixa: true,
        celula: (estado) => (
          <Link href={`/dashboard/empresa?id=${estado.empresa_id}&aba=sincronismo`} className="block truncate text-tinta underline-offset-4 hover:text-acento hover:underline" title={estado.razao_social}>
            {estado.razao_social}
          </Link>
        ),
      },
      { id: "tipo", cabecalho: "Tipo", celula: (estado) => <Etiqueta tom="neutro">{estado.tipo.toUpperCase()}</Etiqueta> },
      {
        id: "situacao",
        cabecalho: "Situação",
        celula: (estado) => (
          <IndicadorEstado
            {...estadoDaSincronizacao(estado, agora)}
            titulo={estado.motivo_bloqueio ?? (estado.em_andamento ? "consulta em curso" : undefined)}
          />
        ),
      },
      { id: "nsu", cabecalho: "Cursor (NSU)", largura: "min-w-48", celula: (estado) => <ResumoNSU estado={estado} /> },
      {
        id: "pendencia",
        cabecalho: "Pendência",
        alinhamento: "direita",
        numerica: true,
        dica: "Documentos entre o cursor atual e o último NSU conhecido pela SEFAZ",
        celula: (estado) => <span className={estado.pendencia > 0 ? "text-espera" : undefined}>{numero(estado.pendencia)}</span>,
      },
      {
        id: "proxima",
        cabecalho: "Próxima consulta",
        alinhamento: "direita",
        celula: (estado) => (
          <span className="nums whitespace-nowrap text-tinta-suave">
            {contagemRegressiva(estado.proxima_consulta_em, agora) ?? (estado.liberacao_rotulo || "—")}
          </span>
        ),
      },
      {
        id: "ultima",
        cabecalho: "Última consulta",
        alinhamento: "direita",
        ocultaPorPadrao: true,
        celula: (estado) => <DataHora iso={estado.ultima_consulta_em} />,
      },
      {
        id: "bloqueio",
        cabecalho: "Bloqueio",
        celula: (estado) =>
          estado.bloqueado_ate ? (
            <span className="text-espera" title={`Bloqueios seguidos: ${numero(estado.bloqueios_seguidos)}`}>
              {estado.motivo_bloqueio ?? "janela SEFAZ"}
            </span>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
      {
        id: "risco",
        cabecalho: "Risco de perda",
        dica: "Dias sem varrer acima do horizonte de distribuição da SEFAZ: documento pode ficar inacessível",
        celula: (estado) =>
          estado.risco_documento_fora_da_distribuicao ? (
            <Etiqueta tom="erro" titulo={estado.dias_sem_varrer !== null ? `${numero(estado.dias_sem_varrer)} dias sem varrer` : undefined}>
              fora da janela
            </Etiqueta>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
      {
        id: "cota",
        cabecalho: "Cota pontual",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (estado) => numero(estado.cota_pontual_disponivel),
      },
      {
        id: "acoes",
        fixar: "direita",
        cabecalho: "Ações",
        alinhamento: "direita",
        celula: (estado) => (
          <Botao
            variante="sutil"
            tamanho="sm"
            disabled={somenteLeitura || desabilitadas.has(estado.empresa_id)}
            title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : desabilitadas.has(estado.empresa_id) ? bloqueios.get(estado.empresa_id) : "Selecionar só esta empresa"}
            onClick={() => {
              definir({ empresa_ids: String(estado.empresa_id), empresa_id: null, empresa: null });
              topo.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          >
            Selecionar
          </Botao>
        ),
      },
    ],
    [agora, bloqueios, definir, desabilitadas, somenteLeitura]
  );

  const alternarTipo = useCallback(
    (tipo: TipoDocumentoFiscal) => {
      const proximo = new Set(tipos);
      if (proximo.has(tipo)) proximo.delete(tipo);
      else proximo.add(tipo);
      definir({ tipos: TIPOS.filter((item) => proximo.has(item)).join(","), tipo: null });
    },
    [definir, tipos]
  );

  const alternarEmpresa = useCallback(
    (proxima: Set<number>) => {
      definir({ empresa_ids: Array.from(proxima).join(","), empresa_id: null });
    },
    [definir]
  );

  const dadosDoDisparo = useMemo(
    () => ({
      empresa_ids: Array.from(selecionadas),
      tipos: TIPOS.filter((tipo) => tipos.has(tipo)),
      ...paraFiltro(periodo),
      forcar,
    }),
    [forcar, periodo, selecionadas, tipos]
  );

  // Id do texto visível que explica o botão desabilitado. O motivo existia só
  // em `title`: quem navega por teclado ou leitor de tela não descobria por que
  // a ação principal estava travada (e a ação que a libera fica no fim da página).
  const idMotivoIndisponivel = useId();
  const podeDisparar = pronto && dadosDoDisparo.empresa_ids.length > 0 && dadosDoDisparo.tipos.length > 0 && !somenteLeitura;
  const motivoIndisponivel = somenteLeitura
    ? MOTIVO_SOMENTE_LEITURA
    : !pronto
      ? "Informe o período da captura"
      : dadosDoDisparo.empresa_ids.length === 0
        ? "Selecione ao menos uma empresa"
        : dadosDoDisparo.tipos.length === 0
          ? "Selecione ao menos um tipo de documento"
          : undefined;

  async function verPrevia() {
    setEnviando("previa");
    setErroAcao(null);
    try {
      const dados = await api.previaImportacaoSelecionadas(dadosDoDisparo);
      setResultado({ modo: "previa", dados });
    } catch (falha) {
      setErroAcao(mensagemDoErro(falha, "calcular a prévia"));
    } finally {
      setEnviando(null);
    }
  }

  async function disparar() {
    setEnviando("disparo");
    setErroAcao(null);
    try {
      const dados = await api.importarSelecionadas(dadosDoDisparo);
      setResultado({ modo: "resultado", dados });
      setConfirmando(false);
      avisar(avisoDoDisparo(dados, rotuloPeriodo(periodo)));
      estados.atualizar();
      resumoSync.atualizar();
      atualizarAlertas();
    } catch (falha) {
      setErroAcao(mensagemDoErro(falha, "disparar a importação"));
      avisar({ tom: "erro", titulo: "A importação não foi disparada", descricao: mensagemDoErro(falha, "disparar a importação") });
    } finally {
      setEnviando(null);
    }
  }

  return (
    <div className="space-y-5" ref={topo}>
      <CabecalhoPagina
        kicker="Fiscal · Captura"
        titulo="Importações"
        descricao="A captura automática mostra o que está em dia, o que aguarda janela e o que precisa ser disparado."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao
              variante="secundaria"
              onClick={verPrevia}
              carregando={enviando === "previa"}
              disabled={!podeDisparar}
              title={motivoIndisponivel}
              aria-describedby={!podeDisparar ? idMotivoIndisponivel : undefined}
            >
              Ver prévia
            </Botao>
            <Botao
              /* Com a prévia ou o resultado na tela, o disparo é o botão
                 daquele cartão — dois "Disparar captura" primários ao mesmo
                 tempo seriam duas ações principais para a mesma decisão. */
              variante={resultado ? "secundaria" : "primaria"}
              onClick={() => setConfirmando(true)}
              carregando={enviando === "disparo"}
              disabled={!podeDisparar}
              title={motivoIndisponivel}
              aria-describedby={!podeDisparar ? idMotivoIndisponivel : undefined}
              iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}
            >
              Disparar captura
            </Botao>
            <MenuSuspenso
              rotulo="Mais ações"
              icone="mais"
              dica="Mais ações de importação"
              itens={[
                {
                  id: "importar-xmls",
                  rotulo: "Importar XMLs de outro sistema…",
                  icone: "documento",
                  desabilitado: somenteLeitura,
                  motivo: somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined,
                  aoClicar: () => setImportacaoXmlAberta(true),
                },
              ]}
            />
          </div>
        }
      />

      {!podeDisparar ? (
        <Aviso id={idMotivoIndisponivel} tom="espera">
          {motivoIndisponivel}. A captura continua automática para as empresas já habilitadas.
        </Aviso>
      ) : null}

      {somenteLeitura ? (
        <Aviso tom="info" icone="cadeado" titulo="Seu papel é somente leitura">
          {MOTIVO_SOMENTE_LEITURA} Você ainda pode consultar período, empresas e estado do sincronismo.
        </Aviso>
      ) : null}

      {erroAcao ? (
        <Aviso tom="erro" titulo="Não deu para continuar" aoFechar={() => setErroAcao(null)}>
          {erroAcao}
        </Aviso>
      ) : null}

      <Cartao
        titulo="Captura automática"
        descricao="Onde a captura está e o que ainda aguarda a SEFAZ"
        acoes={
          <BotaoLink href="/dashboard/execucoes?aba=fila" variante="link" tamanho="sm">
            Próximas janelas
          </BotaoLink>
        }
      >
          {resumoSync.carregando ? (
            <EsqueletoBloco linhas={6} />
          ) : resumoSync.erro ? (
            <EstadoErro erro={resumoSync.erro} aoTentarNovamente={resumoSync.atualizar} contexto="carregar o resumo do sincronismo" />
          ) : resumoSync.dados ? (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
                <Dado destaque rotulo="Empresas" valor={numero(resumoSync.dados.empresas)} />
                <Dado destaque rotulo="Combinações" valor={`${numero(resumoSync.dados.em_dia)}/${numero(resumoSync.dados.combinacoes)}`} contexto="em dia" />
                <Dado destaque rotulo="Com pendência" valor={numero(resumoSync.dados.com_pendencia)} tom={resumoSync.dados.com_pendencia > 0 ? "espera" : undefined} />
                <Dado destaque rotulo="Em andamento" valor={numero(resumoSync.dados.em_andamento)} />
                <Dado destaque rotulo="Aguardando janela" valor={numero(resumoSync.dados.aguardando_janela)} tom={resumoSync.dados.aguardando_janela > 0 ? "espera" : undefined} />
                <Dado destaque rotulo="Bloqueadas pela SEFAZ" valor={numero(resumoSync.dados.bloqueadas_sefaz)} tom={resumoSync.dados.bloqueadas_sefaz > 0 ? "erro" : undefined} />
                <Dado destaque rotulo="Documentos no banco" valor={numero(resumoSync.dados.documentos_no_banco)} />
                <Dado
                  destaque
                  rotulo="Varredura automática"
                  valor={resumoSync.dados.sincronismo_automatico ? `a cada ${numero(resumoSync.dados.intervalo_minutos)} min` : "desligada"}
                  tom={resumoSync.dados.sincronismo_automatico ? undefined : "espera"}
                />
                <Dado
                  destaque
                  rotulo="Próxima varredura"
                  valor={rotuloProximaVarredura(
                    resumoSync.dados.sincronismo_automatico,
                    resumoSync.dados.tick_a_partir_de,
                    agora
                  )}
                />
              </dl>
              {certificados.dados && certificados.dados.some((certificado) => !certificado.tem_certificado || certificado.vencido) ? (
                <p className="mt-4 border-t border-traco pt-3 text-sm text-espera">
                  {numero(certificados.dados.filter((certificado) => !certificado.tem_certificado).length)} empresas sem certificado e{" "}
                  {numero(certificados.dados.filter((certificado) => certificado.vencido).length)} com certificado vencido não podem ser capturadas.{" "}
                  <Link href="/dashboard/certificados" className="link-prosa font-medium">
                    Resolver em Certificados
                  </Link>
                  .
                </p>
              ) : null}
            </>
          ) : null}
        </Cartao>

      <Cartao
        titulo="Período e tipos"
        descricao="O período é obrigatório: é ele que define o que será guardado no acervo."
        acoes={
          <span className="nums text-xs text-tinta-suave">
            {contagem(selecionadas.size, "empresa", "empresas")} · {contagem(tipos.size, "tipo", "tipos")}
          </span>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
          <SeletorPeriodo periodo={periodo} aoMudar={aoMudarPeriodo} obrigatorio />
          <div>
            <p className="mb-1.5 text-xs font-medium text-tinta">Tipos de documento</p>
            <div className="flex flex-wrap gap-4">
              {TIPOS.map((tipo) => (
                <Caixa
                  key={tipo}
                  rotulo={ROTULO_TIPO[tipo]}
                  compacta
                  checked={tipos.has(tipo)}
                  onChange={() => alternarTipo(tipo)}
                  disabled={somenteLeitura}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-4 border-t border-traco pt-3">
          <Alternador
            rotulo="Ignorar cursor e janela (forçar)"
            descricao="Revarre o período inteiro mesmo sem NSU novo. Consome cota da SEFAZ e pode repetir consultas — use só quando houver documento faltando."
            ligado={forcar}
            aoMudar={(valor) => definir({ forcar: valor ? "1" : null })}
            desabilitado={somenteLeitura}
            motivoDesabilitado={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
          />
        </div>
      </Cartao>

      <Cartao
        titulo="Empresas"
        descricao="Marque quem deve ser capturado. Sem certificado A1 válido a empresa fica bloqueada."
        acoes={
          selecionadas.size > 0 ? (
            <Botao
              variante="link-sutil"
              tamanho="sm"
              onClick={() => definir({ empresa_ids: null, empresa_id: null })}
            >
              Limpar seleção
            </Botao>
          ) : undefined
        }
      >
        {empresas.carregando ? (
          <EsqueletoBloco linhas={6} />
        ) : empresas.erro ? (
          <EstadoErro erro={empresas.erro} aoTentarNovamente={empresas.atualizar} contexto="carregar as empresas" />
        ) : (
          <SeletorEmpresas
            empresas={empresas.dados ?? []}
            selecionadas={selecionadas}
            aoMudar={alternarEmpresa}
            situacoes={situacoes}
            bloqueios={bloqueios}
            desabilitadas={desabilitadas}
            altura={360}
          />
        )}
      </Cartao>

      {resultado ? (
        <Cartao
          titulo={resultado.modo === "previa" ? "Prévia do disparo" : "Resultado do disparo"}
          descricao={
            resultado.modo === "previa"
              ? "Nada foi enviado à SEFAZ ainda — é a leitura local do que aconteceria."
              : "Situação de cada empresa e tipo neste disparo."
          }
          acoes={
            <Botao variante="link-sutil" tamanho="sm" onClick={() => setResultado(null)}>
              Fechar
            </Botao>
          }
        >
          <ResumoImportacao resultado={resultado.dados} modo={resultado.modo} />
          {resultado.modo === "resultado" && resultado.dados.enfileiradas > 0 ? (
            // Fecha o laço: disparado, o operador precisa saber onde ver o
            // resultado — a captura roda na SEFAZ e os documentos caem na lista
            // conforme chegam, não neste instante.
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-traco pt-3">
              <p className="max-w-leitura text-sm leading-6 text-tinta-suave">
                {contagem(resultado.dados.enfileiradas, "captura está rodando", "capturas estão rodando")} em
                segundo plano. Os documentos entram na lista conforme chegam — ela avisa enquanto isso.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <BotaoLink variante="secundaria" tamanho="sm" href="/dashboard/documentos">
                  Ver documentos
                </BotaoLink>
                <BotaoLink variante="link" tamanho="sm" href="/dashboard/execucoes?aba=fila">
                  Acompanhar na central
                </BotaoLink>
              </div>
            </div>
          ) : null}

          {resultado.modo === "previa" && resultado.dados.enfileiradas > 0 ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-traco pt-3">
              <p className="text-sm text-tinta-suave">
                {contagem(resultado.dados.enfileiradas, "captura será enfileirada", "capturas serão enfileiradas")} ·{" "}
                {contagem(resultado.dados.aguardando, "ficará aguardando janela", "ficarão aguardando janela")}.
              </p>
              <Botao
                variante="primaria"
                onClick={() => setConfirmando(true)}
                disabled={!podeDisparar}
                title={motivoIndisponivel}
                aria-describedby={!podeDisparar ? idMotivoIndisponivel : undefined}
              >
                Disparar captura
              </Botao>
            </div>
          ) : null}
        </Cartao>
      ) : null}

      <Tabela
        linhas={linhasSincronismo}
        colunas={colunas}
        chaveDaLinha={(estado) => `${estado.empresa_id}-${estado.tipo}`}
        legenda="Sincronismo por empresa e tipo"
        virtualizar
        estados={{
          carregando: estados.carregando,
          erro: estados.erro,
          aoTentarNovamente: estados.atualizar,
          vazioTitulo: "Nenhuma combinação com este recorte",
          vazioInstrucao: "Cadastre empresas e certificados A1 para que o sincronismo apareça aqui.",
          vazioAcao: (
            <BotaoLink variante="secundaria" href="/dashboard/empresas">
              Ver empresas
            </BotaoLink>
          ),
          vazioIcone: "sincronizar",
          filtroAtivo: Boolean(ler("sinc_empresa") || ler("sinc_situacao")),
          aoLimparFiltro: () => definir({ sinc_empresa: null, sinc_situacao: null }),
        }}
        ferramentas={
          <div className="flex flex-wrap items-end gap-2">
            <Selecao
              rotulo="Empresa"
              className="w-56"
              value={ler("sinc_empresa")}
              onChange={(evento) => definir({ sinc_empresa: evento.target.value || null })}
              opcoes={[
                { valor: "", rotulo: "Todas as empresas" },
                ...(empresas.dados ?? []).map((empresa) => ({ valor: String(empresa.id), rotulo: empresa.razao_social })),
              ]}
            />
            <Selecao
              rotulo="Situação"
              className="w-52"
              value={ler("sinc_situacao")}
              onChange={(evento) => definir({ sinc_situacao: evento.target.value || null })}
              opcoes={[
                { valor: "", rotulo: "Todas as situações" },
                { valor: "pendencia", rotulo: "Com pendência" },
                { valor: "em_dia", rotulo: "Em dia" },
                { valor: "bloqueada", rotulo: "Bloqueada pela SEFAZ" },
                { valor: "risco", rotulo: "Risco de perda" },
                { valor: "manual", rotulo: "Sincronismo manual" },
              ]}
            />
          </div>
        }
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {contagem(linhasSincronismo.length, "combinação", "combinações")} empresa × tipo
          </p>
        }
      />

      <ModalImportarXmls
        aberto={importacaoXmlAberta}
        aoFechar={() => setImportacaoXmlAberta(false)}
        aoConcluir={() => {
          resumoSync.atualizar();
          estados.atualizar();
        }}
      />

      <DialogoConfirmacao
        aberto={confirmando}
        aoFechar={() => setConfirmando(false)}
        aoConfirmar={disparar}
        carregando={enviando === "disparo"}
        erro={erroAcao}
        titulo="Disparar captura"
        consequencia={
          <span>
            {contagem(dadosDoDisparo.empresa_ids.length, "empresa", "empresas")} ×{" "}
            {dadosDoDisparo.tipos.map((tipo) => ROTULO_TIPO[tipo]).join(", ")} no período {rotuloPeriodo(periodo)}
            {forcar ? ", ignorando o cursor atual" : ""}.
          </span>
        }
        impacto={
          <span>
            Cada consulta usa a janela de 1 hora da SEFAZ para a combinação empresa × tipo. Itens já em espera ou bloqueados voltam como
            “aguardando”, não como erro. Documentos já importados não são duplicados.
          </span>
        }
        aviso={
          forcar ? (
            <span className="text-espera">
              Com “forçar” ligado, o período inteiro é revarrido: o consumo de cota é maior e o resultado pode repetir consultas.
            </span>
          ) : undefined
        }
        rotuloConfirmar="Disparar"
        tom="normal"
      />
    </div>
  );
}

