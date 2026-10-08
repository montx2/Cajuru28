"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { contagem, dataCurta, formatarCnpjCpf, numero, plural, somenteDigitos } from "@/lib/format";
import {
  ATRIBUTOS_SELETOR_DE_PASTA,
  LIMITE_CERTIFICADOS_POR_LOTE,
  certificadosDaPasta,
} from "@/lib/pastaCertificados";
import { estadoDaSincronizacao, estadoDoCertificado, type EstadoVisual } from "@/lib/estados";
import { mensagemDoErro, problemasDeValidacao } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { paraFiltro, rotuloPeriodo } from "@/lib/periodo";
import { UFS } from "@/lib/uf";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { usePeriodoUrl } from "@/lib/usePeriodoUrl";
import { usePreferencia } from "@/lib/usePreferencia";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { ModalImportarXmls } from "@/app/dashboard/importacoes/ImportarXmls";
import { Botao } from "@/components/ui/Botao";
import { Aviso } from "@/components/ui/Aviso";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Formulario } from "@/components/ui/Formulario";
import { ErroDoCampo } from "@/components/ui/Campo";
import { Busca, Caixa, Entrada, Selecao } from "@/components/ui/Campo";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { Dado } from "@/components/ui/Dado";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, DataHora, ValorMoeda } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { MenuSuspenso } from "@/components/ui/MenuSuspenso";
import { Modal } from "@/components/ui/Modal";
import { Tabela, type ColunaTabela, type DensidadeTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import type { Empresa, EmpresaResumoDocumentos, ItemLoteEmpresas, LoteEmpresasResposta, ResumoCertificado } from "@/lib/types";
import { ROTULO_STATUS_LOTE } from "@/lib/types";

type SituacaoFiltro = "" | "ativas" | "inativas" | "sem_certificado" | "certificado_vencido" | "certificado_vencendo" | "com_pendencia" | "bloqueada" | "sem_documento_mes";

const SITUACOES: Array<{ valor: SituacaoFiltro; rotulo: string }> = [
  { valor: "", rotulo: "Todas as situações" },
  { valor: "ativas", rotulo: "Ativas" },
  { valor: "inativas", rotulo: "Inativas" },
  { valor: "sem_certificado", rotulo: "Sem certificado A1" },
  { valor: "certificado_vencido", rotulo: "Certificado vencido" },
  { valor: "certificado_vencendo", rotulo: "Certificado vencendo" },
  { valor: "com_pendencia", rotulo: "Com pendência na SEFAZ" },
  { valor: "bloqueada", rotulo: "Bloqueada pela SEFAZ" },
  { valor: "sem_documento_mes", rotulo: "Sem documento no mês" },
];

interface LinhaEmpresa {
  empresa: Empresa;
  certificado: ResumoCertificado | null;
  pendencia: number;
  bloqueada: boolean;
  automatica: boolean;
  sincronismo: EstadoVisual | null;
  resumo: EmpresaResumoDocumentos | null;
}

/**
 * Cadastro de empresas: quem pode ser capturado e com qual certificado.
 *
 * A coluna de documentos do mês vem de `/documentos/por-empresa` porque a
 * pergunta real desta tela é "alguma empresa minha ficou muda?" — e isso só se
 * vê comparando cadastro, certificado e volume capturado no mesmo lugar.
 */
export function Empresas() {
  const router = useRouter();
  const { definir, ler } = useUrlEstado();
  const busca = useBuscaUrl();
  const { periodo, pronto } = usePeriodoUrl();
  const { somenteLeitura } = useSessao();
  const agora = useAgora();

  const situacao = ler("situacao") as SituacaoFiltro;
  const ordem = ler("ordem") || "razao";
  const sentido = ler("sentido") === "desc" ? "desc" : "asc";

  const [densidade, setDensidade] = usePreferencia<DensidadeTabela>("empresas-densidade", "confortavel");
  const [colunasVisiveis, setColunasVisiveis] = usePreferencia<string[] | null>("empresas-colunas", null);
  const [novaAberta, setNovaAberta] = useState(false);
  const [loteAberto, setLoteAberto] = useState(false);
  const [importacaoXmlAberta, setImportacaoXmlAberta] = useState(false);
  const [colunasAbertas, setColunasAbertas] = useState(false);

  const empresas = useRecurso(() => api.listarEmpresas(), []);
  const certificados = useRecurso(() => api.resumoCertificados(), []);
  const estados = useRecurso(() => api.estadoSincronizacao(), []);
  const resumos = useRecurso(() => api.resumoPorEmpresa(paraFiltro(periodo)), [periodo.inicio, periodo.fim], { automatico: pronto });

  useSinalizarAtualizacao(empresas.atualizando || certificados.atualizando || resumos.atualizando);

  function recarregar() {
    empresas.atualizar();
    certificados.atualizar();
    estados.atualizar();
    resumos.atualizar();
  }

  const linhas = useMemo<LinhaEmpresa[]>(() => {
    const certificadoPorEmpresa = new Map<number, ResumoCertificado>();
    for (const certificado of certificados.dados ?? []) certificadoPorEmpresa.set(certificado.empresa_id, certificado);

    const sincronismoPorEmpresa = new Map<number, { pendencia: number; bloqueada: boolean; automatica: boolean; pior: EstadoVisual | null }>();
    const prioridade: Record<string, number> = { erro: 0, espera: 1, info: 2, neutro: 3, acento: 4, ok: 5 };
    for (const estado of estados.dados ?? []) {
      const visual = estadoDaSincronizacao(estado, agora);
      const atual = sincronismoPorEmpresa.get(estado.empresa_id);
      const pior = !atual?.pior || (prioridade[visual.tom] ?? 9) < (prioridade[atual.pior.tom] ?? 9) ? visual : atual.pior;
      sincronismoPorEmpresa.set(estado.empresa_id, {
        pendencia: (atual?.pendencia ?? 0) + estado.pendencia,
        bloqueada: Boolean(atual?.bloqueada) || Boolean(estado.bloqueado_ate),
        automatica: Boolean(atual?.automatica) || estado.sincronizar_automaticamente,
        pior,
      });
    }

    const resumoPorEmpresa = new Map<number, EmpresaResumoDocumentos>();
    for (const resumo of resumos.dados ?? []) resumoPorEmpresa.set(resumo.empresa_id, resumo);

    return (empresas.dados ?? []).map((empresa) => {
      const sincronismo = sincronismoPorEmpresa.get(empresa.id);
      return {
        empresa,
        certificado: certificadoPorEmpresa.get(empresa.id) ?? null,
        pendencia: sincronismo?.pendencia ?? 0,
        bloqueada: sincronismo?.bloqueada ?? false,
        automatica: sincronismo?.automatica ?? Boolean(empresa.sincronizar_automaticamente),
        sincronismo: sincronismo?.pior ?? null,
        resumo: resumoPorEmpresa.get(empresa.id) ?? null,
      };
    });
  }, [agora, certificados.dados, empresas.dados, estados.dados, resumos.dados]);

  const filtradas = useMemo(() => {
    const termo = busca.valor.trim().toLocaleLowerCase("pt-BR");
    const digitos = termo.replace(/\D/g, "");
    const resultado = linhas.filter((linha) => {
      const { empresa, certificado } = linha;
      if (termo) {
        const casaTexto = `${empresa.razao_social} ${empresa.uf ?? ""}`.toLocaleLowerCase("pt-BR").includes(termo);
        const casaCnpj = digitos.length >= 2 && somenteDigitos(empresa.cnpj_cpf).includes(digitos);
        if (!casaTexto && !casaCnpj) return false;
      }
      switch (situacao) {
        case "ativas":
          return empresa.ativa;
        case "inativas":
          return !empresa.ativa;
        case "sem_certificado":
          return !certificado?.tem_certificado;
        case "certificado_vencido":
          return Boolean(certificado?.vencido);
        case "certificado_vencendo":
          return Boolean(certificado?.vence_em_breve);
        case "com_pendencia":
          return linha.pendencia > 0;
        case "bloqueada":
          return linha.bloqueada;
        case "sem_documento_mes":
          return (linha.resumo?.total ?? 0) === 0;
        default:
          return true;
      }
    });
    const fator = sentido === "asc" ? 1 : -1;
    return [...resultado].sort((a, b) => fator * compararLinhas(a, b, ordem));
  }, [busca.valor, linhas, ordem, sentido, situacao]);

  const colunas = useMemo<Array<ColunaTabela<LinhaEmpresa>>>(
    () => [
      {
        id: "razao",
        cabecalho: "Razão social",
        largura: "min-w-64",
        fixa: true,
        ordenavel: true,
        celula: (linha) => (
          <span className="block truncate font-medium text-tinta-forte" title={linha.empresa.razao_social}>
            {linha.empresa.razao_social}
          </span>
        ),
      },
      { id: "cnpj", cabecalho: "CNPJ", largura: "min-w-52", ordenavel: true, celula: (linha) => <Cnpj valor={linha.empresa.cnpj_cpf} /> },
      { id: "uf", cabecalho: "UF", largura: "w-14 min-w-14", ordenavel: true, celula: (linha) => <span className="nums text-tinta-suave">{linha.empresa.uf || "—"}</span> },
      {
        id: "situacao",
        cabecalho: "Cadastro",
        ordenavel: true,
        celula: (linha) =>
          linha.empresa.ativa ? (
            <IndicadorEstado tom="ok" rotulo="Ativa" icone="verificar-circulo" />
          ) : (
            <IndicadorEstado tom="neutro" rotulo="Inativa" icone="pausa" titulo="Empresa inativa não entra na captura automática" />
          ),
      },
      {
        id: "certificado",
        cabecalho: "Certificado A1",
        largura: "min-w-44",
        ordenavel: true,
        celula: (linha) =>
          linha.certificado ? (
            <IndicadorEstado {...estadoDoCertificado(linha.certificado)} titulo={linha.certificado.validade ? `Validade ${dataCurta(linha.certificado.validade)}` : undefined} />
          ) : (
            <IndicadorEstado tom="erro" rotulo="Sem certificado A1" icone="certificado" />
          ),
      },
      {
        id: "sincronismo",
        cabecalho: "Sincronismo",
        largura: "min-w-40",
        ordenavel: true,
        celula: (linha) =>
          linha.sincronismo ? (
            <IndicadorEstado {...linha.sincronismo} detalhe={linha.pendencia > 0 ? <span className="nums">· {contagem(linha.pendencia, "pendente", "pendentes")}</span> : undefined} />
          ) : (
            <span className="text-tinta-fraca">sem histórico</span>
          ),
      },
      {
        id: "documentos",
        cabecalho: `Documentos · ${rotuloPeriodo(periodo)}`,
        alinhamento: "direita",
        numerica: true,
        ordenavel: true,
        celula: (linha) => (
          <span className={linha.resumo && linha.resumo.total === 0 ? "text-espera" : undefined}>{numero(linha.resumo?.total ?? 0)}</span>
        ),
      },
      {
        id: "sem_xml",
        cabecalho: "Sem XML completo",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (linha) => numero(linha.resumo?.sem_xml_completo ?? 0),
      },
      {
        id: "canceladas",
        cabecalho: "Canceladas",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (linha) => numero(linha.resumo?.canceladas ?? 0),
      },
      {
        id: "valor",
        cabecalho: "Valor no mês",
        ocultaPorPadrao: true,
        alinhamento: "direita",
        numerica: true,
        ordenavel: true,
        celula: (linha) => <ValorMoeda valor={linha.resumo?.valor_total ?? null} />,
      },
      {
        id: "tipos",
        cabecalho: "Tipos sincronizados",
        ocultaPorPadrao: true,
        celula: (linha) => {
          const tipos = (linha.empresa.quais_tipos_sincronizar ?? "").split(",").filter(Boolean);
          return tipos.length > 0 ? (
            <span className="flex flex-wrap gap-1">
              {tipos.map((tipo) => (
                <Etiqueta key={tipo} tom="neutro">
                  {tipo.trim().toUpperCase()}
                </Etiqueta>
              ))}
            </span>
          ) : (
            <span className="text-tinta-fraca">todos</span>
          );
        },
      },
      {
        id: "criado",
        cabecalho: "Cadastrada",
        alinhamento: "direita",
        ordenavel: true,
        ocultaPorPadrao: true,
        celula: (linha) => <DataHora iso={linha.empresa.criado_em} />,
      },
    ],
    [periodo]
  );

  const filtroAtivo = Boolean(situacao || busca.valor.trim());

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        kicker="Fiscal · Cadastro"
        titulo="Empresas"
        descricao="Cadastro, certificado A1 e volume capturado de cada CNPJ do escritório."
        acoes={
            <Botao
              variante="primaria"
              onClick={() => setNovaAberta(true)}
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="adicionar" className="h-3.5 w-3.5" />}
            >
              Nova empresa
            </Botao>
        }
      />

      <Tabela
        linhas={filtradas}
        colunas={colunas}
        chaveDaLinha={(linha) => linha.empresa.id}
        legenda="Empresas do escritório"
        aoAbrirLinha={(linha) => router.push(`/dashboard/empresa?id=${linha.empresa.id}`)}
        ordenacao={{ coluna: ordem, direcao: sentido }}
        aoOrdenar={(proxima) => definir({ ordem: proxima?.coluna ?? null, sentido: proxima?.direcao ?? null })}
        densidade={densidade}
        colunasVisiveis={colunasVisiveis ?? undefined}
        estados={{
          carregando: empresas.carregando,
          erro: empresas.erro,
          aoTentarNovamente: empresas.atualizar,
          vazioTitulo: "Nenhuma empresa com este recorte",
          vazioInstrucao: "Cadastre a primeira empresa com CNPJ e certificado A1 para começar a capturar documentos.",
          vazioAcao: somenteLeitura ? undefined : (
            <Botao variante="secundaria" onClick={() => setNovaAberta(true)} iconeEsquerda={<Icone nome="adicionar" className="h-4 w-4" />}>
              Nova empresa
            </Botao>
          ),
          vazioIcone: "empresa",
          filtroAtivo,
          aoLimparFiltro: filtroAtivo
            ? () => {
                definir({ situacao: null, busca: null });
                busca.aoMudar("");
              }
            : undefined,
        }}
        ferramentas={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Busca rotulo="Buscar empresa" placeholder="Razão social ou CNPJ" valor={busca.valor} aoMudar={busca.aoMudar} className="w-full sm:min-w-64 sm:flex-1" />

            <MenuSuspenso
              rotulo="Mais ações e filtros"
              icone="mais"
              dica="Mais ações e filtros"
              itens={[
                ...SITUACOES.map((opcao) => ({
                  id: `situacao-${opcao.valor || "todas"}`,
                  rotulo: opcao.rotulo,
                  icone: "filtrar" as const,
                  selecionado: situacao === opcao.valor,
                  aoClicar: () => definir({ situacao: opcao.valor || null }),
                })),
                {
                  id: "certificados",
                  rotulo: "Importar certificados em lote…",
                  icone: "certificado",
                  separarAcima: true,
                  desabilitado: somenteLeitura,
                  motivo: somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined,
                  aoClicar: () => setLoteAberto(true),
                },
                {
                  id: "xmls",
                  rotulo: "Importar XMLs de outro sistema…",
                  icone: "documento",
                  desabilitado: somenteLeitura,
                  motivo: somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined,
                  aoClicar: () => setImportacaoXmlAberta(true),
                },
                {
                  id: "colunas",
                  rotulo: "Escolher colunas…",
                  icone: "colunas",
                  separarAcima: true,
                  aoClicar: () => setColunasAbertas(true),
                },
                {
                  id: "densidade",
                  rotulo: densidade === "compacta" ? "Usar linhas confortáveis" : "Usar linhas compactas",
                  icone: "menu",
                  aoClicar: () => setDensidade(densidade === "compacta" ? "confortavel" : "compacta"),
                },
              ]}
            />
          </div>
        }
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {contagem(filtradas.length, "empresa", "empresas")} · {numero(linhas.filter((linha) => !linha.certificado?.tem_certificado).length)} sem certificado ·{" "}
            {numero(linhas.filter((linha) => linha.pendencia > 0).length)} com pendência
          </p>
        }
      />

      <ModalNovaEmpresa aberto={novaAberta} aoFechar={() => setNovaAberta(false)} aoCriar={recarregar} />
      <ModalImportacaoLote aberto={loteAberto} aoFechar={() => setLoteAberto(false)} aoImportar={recarregar} />
      <ModalImportarXmls aberto={importacaoXmlAberta} aoFechar={() => setImportacaoXmlAberta(false)} aoConcluir={recarregar} />
      <Modal
        aberto={colunasAbertas}
        aoFechar={() => setColunasAbertas(false)}
        titulo="Colunas da tabela"
        descricao="Escolha quais dados aparecem sem alterar o cadastro."
        largura="estreita"
        rodape={
          <div className="flex items-center justify-between gap-2">
            <Botao variante="sutil" onClick={() => setColunasVisiveis(colunas.map((coluna) => coluna.id))}>Mostrar todas</Botao>
            <Botao variante="secundaria" onClick={() => setColunasAbertas(false)}>Concluir</Botao>
          </div>
        }
      >
        <div className="space-y-1">
          {colunas.map((coluna) => (
            <Caixa
              key={coluna.id}
              rotulo={coluna.cabecalho}
              checked={coluna.fixa || (colunasVisiveis ? colunasVisiveis.includes(coluna.id) : !coluna.ocultaPorPadrao)}
              disabled={coluna.fixa}
              onChange={(evento) => {
                const atuais = colunasVisiveis ?? colunas.filter((item) => item.fixa || !item.ocultaPorPadrao).map((item) => item.id);
                setColunasVisiveis(
                  evento.target.checked
                    ? colunas.map((item) => item.id).filter((id) => id === coluna.id || atuais.includes(id))
                    : atuais.filter((id) => id !== coluna.id)
                );
              }}
            />
          ))}
        </div>
      </Modal>
    </div>
  );
}

function compararLinhas(a: LinhaEmpresa, b: LinhaEmpresa, coluna: string): number {
  switch (coluna) {
    case "razao":
      return a.empresa.razao_social.localeCompare(b.empresa.razao_social, "pt-BR");
    case "cnpj":
      return somenteDigitos(a.empresa.cnpj_cpf).localeCompare(somenteDigitos(b.empresa.cnpj_cpf));
    case "uf":
      return (a.empresa.uf ?? "").localeCompare(b.empresa.uf ?? "");
    case "situacao":
      return Number(b.empresa.ativa) - Number(a.empresa.ativa);
    case "certificado":
      return (a.certificado?.dias_para_vencer ?? -1) - (b.certificado?.dias_para_vencer ?? -1);
    case "sincronismo":
      return b.pendencia - a.pendencia;
    case "documentos":
      return (a.resumo?.total ?? 0) - (b.resumo?.total ?? 0);
    case "valor":
      return (a.resumo?.valor_total ?? 0) - (b.resumo?.valor_total ?? 0);
    case "criado":
      return new Date(a.empresa.criado_em).getTime() - new Date(b.empresa.criado_em).getTime();
    default:
      return 0;
  }
}

function ModalNovaEmpresa({ aberto, aoFechar, aoCriar }: { aberto: boolean; aoFechar: () => void; aoCriar: () => void }) {
  const { avisar } = useToast();
  const [razao, setRazao] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [uf, setUf] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [consultando, setConsultando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [nota, setNota] = useState<string | null>(null);
  const [errosCampo, setErrosCampo] = useState<{ razao?: string; cnpj?: string; uf?: string }>({});

  function limpar() {
    setRazao("");
    setCnpj("");
    setUf("");
    setErro(null);
    setNota(null);
    setErrosCampo({});
  }

  function fechar() {
    limpar();
    aoFechar();
  }

  async function consultarCnpj() {
    const documentoLimpo = cnpj.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
    if (documentoLimpo.length !== 14 && documentoLimpo.length !== 11) {
      setErrosCampo((atual) => ({ ...atual, cnpj: "Informe um CNPJ (14 caracteres) ou CPF (11 dígitos) para consultar." }));
      return;
    }
    setConsultando(true);
    setErro(null);
    setNota(null);
    try {
      const consulta = await api.consultarCnpj(documentoLimpo);
      if (consulta.encontrado) {
        const razaoEncontrada = consulta.razao_social || consulta.nome_fantasia || razao;
        const ufEncontrada = consulta.uf || uf;
        setRazao(razaoEncontrada);
        setUf(ufEncontrada);
        setErrosCampo({});
        setNota(`Encontrado via ${consulta.fonte}${consulta.municipio ? ` · ${consulta.municipio}` : ""}.`);
      } else {
        setNota(consulta.mensagem || "CNPJ não encontrado na fonte consultada — preencha a razão social manualmente.");
      }
    } catch (falha) {
      setNota(mensagemDoErro(falha, "consultar o CNPJ"));
    } finally {
      setConsultando(false);
    }
  }

  async function enviar() {
    const documentoLimpo = cnpj.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
    const ehCnpjNumerico = /^\d{14}$/.test(documentoLimpo);
    const proximosErros: typeof errosCampo = {};
    if (documentoLimpo.length !== 14 && documentoLimpo.length !== 11) {
      proximosErros.cnpj = "CNPJ tem 14 caracteres; CPF, 11 dígitos.";
    }
    if (!razao.trim() && !ehCnpjNumerico) {
      proximosErros.razao = "Informe a razão social como consta no certificado.";
    }
    setErrosCampo(proximosErros);
    if (Object.keys(proximosErros).length > 0) return;

    setEnviando(true);
    setErro(null);
    try {
      const criada = await api.criarEmpresa(razao.trim(), documentoLimpo, uf || undefined);
      avisar({ tom: "ok", titulo: "Empresa cadastrada", descricao: `${criada.razao_social} · ${formatarCnpjCpf(criada.cnpj_cpf)}` });
      aoCriar();
      fechar();
    } catch (falha) {
      const msg = mensagemDoErro(falha, "cadastrar a empresa");
      setErro(msg);
      // O destaque do campo vem do `loc` estruturado da API. Antes o código
      // varria o texto do erro procurando "UF"/"razão social": o mesmo erro
      // ganhava duas mensagens (a do servidor e a inventada aqui) e qualquer
      // texto que citasse "UF" acendia o campo errado.
      for (const problema of problemasDeValidacao(falha)) {
        const campo = problema.campo.split(" → ").pop() ?? "";
        if (campo === "razao_social" && !razao.trim()) {
          setErrosCampo((atual) => ({ ...atual, razao: "Informe a razão social como consta no certificado." }));
        }
        if (campo === "uf" && !uf) {
          setErrosCampo((atual) => ({ ...atual, uf: "Selecione a UF da empresa." }));
        }
        if (campo === "cnpj_cpf") {
          setErrosCampo((atual) => ({ ...atual, cnpj: problema.mensagem }));
        }
      }
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={fechar}
      titulo="Nova empresa"
      descricao="Depois de cadastrar, envie o certificado A1 na tela da empresa para liberar a captura."
      largura="media"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={fechar}>
            Cancelar
          </Botao>
          <Botao variante="primaria" onClick={enviar} carregando={enviando} iconeEsquerda={<Icone nome="adicionar" className="h-4 w-4" />}>
            Cadastrar empresa
          </Botao>
        </div>
      }
    >
      <Formulario aoEnviar={enviar} ocupado={enviando} className="space-y-4">
        <Entrada
          rotulo="CNPJ ou CPF"
          obrigatorio
          value={cnpj}
          onChange={(evento) => {
            setCnpj(evento.target.value);
            setErro(null);
            if (errosCampo.cnpj) setErrosCampo((atual) => ({ ...atual, cnpj: undefined }));
          }}
          placeholder="00.000.000/0000-00"
          mono
          erro={errosCampo.cnpj ?? null}
          nota={nota}
          inputMode="numeric"
          autoComplete="off"
          acaoRotulo={
            <Botao variante="link" tamanho="sm" onClick={consultarCnpj} disabled={consultando}>
              {consultando ? "Consultando…" : "Consultar CNPJ"}
            </Botao>
          }
        />
        <Entrada
          rotulo="Razão social"
          obrigatorio
          value={razao}
          onChange={(evento) => {
            setRazao(evento.target.value);
            setErro(null);
            if (errosCampo.razao) setErrosCampo((atual) => ({ ...atual, razao: undefined }));
          }}
          erro={errosCampo.razao ?? null}
          descricao="Como consta no certificado A1 — é o nome que aparece nas listas."
        />
        <Selecao
          rotulo="UF"
          value={uf}
          erro={errosCampo.uf ?? null}
          onChange={(evento) => {
            setUf(evento.target.value);
            setErro(null);
            if (errosCampo.uf) setErrosCampo((atual) => ({ ...atual, uf: undefined }));
          }}
          descricao="Opcional: ajuda a localizar a empresa e valida o município do emitente."
          opcoes={[{ valor: "", rotulo: "Não informar" }, ...UFS.map((item) => ({ valor: item.sigla, rotulo: `${item.sigla} · ${item.nome}` }))]}
        />
        {erro ? (
          <Aviso tom="erro" compacto urgente>
            {erro}
          </Aviso>
        ) : null}
      </Formulario>
    </Modal>
  );
}

export function ModalImportacaoLote({ aberto, aoFechar, aoImportar }: { aberto: boolean; aoFechar: () => void; aoImportar: () => void }) {
  const { avisar } = useToast();
  const pastaRef = useRef<HTMLInputElement>(null);
  const [certificados, setCertificados] = useState<File[]>([]);
  const [arquivosIgnorados, setArquivosIgnorados] = useState(0);
  const [substituidosDaPasta, setSubstituidosDaPasta] = useState(0);
  const [planilhas, setPlanilhas] = useState<File[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<LoteEmpresasResposta | null>(null);
  const [completando, setCompletando] = useState(false);

  const senhasNaPlanilha = planilhas.length > 0;
  const acimaDoLote = certificados.length > LIMITE_CERTIFICADOS_POR_LOTE;
  const podeEnviar = certificados.length > 0 && !acimaDoLote;
  const motivoBloqueio =
    certificados.length === 0
      ? "Escolha a pasta (ou os arquivos) dos certificados"
      : acimaDoLote
        ? `A pasta tem ${contagem(certificados.length, "certificado", "certificados")} — o limite por lote é ${LIMITE_CERTIFICADOS_POR_LOTE}. Importe em etapas.`
        : undefined;

  function receberPasta(lista: FileList | null) {
    if (!lista) return;
    const { certificados: encontrados, ignorados, substituidos } = certificadosDaPasta(lista);
    // A pasta substitui a seleção: quem escolheu pasta quer o lote da pasta.
    setCertificados(encontrados);
    setArquivosIgnorados(ignorados);
    setSubstituidosDaPasta(substituidos);
    if (pastaRef.current) pastaRef.current.value = "";
  }

  function limpar() {
    setCertificados([]);
    setArquivosIgnorados(0);
    setSubstituidosDaPasta(0);
    setPlanilhas([]);
    setErro(null);
    setResultado(null);
  }

  function fechar() {
    limpar();
    aoFechar();
  }

  async function enviar() {
    if (!podeEnviar) return;
    setEnviando(true);
    setErro(null);
    try {
      const lote = await api.importarEmpresasEmMassa(certificados, planilhas);
      setResultado(lote);
      avisar({
        tom: lote.erros > 0 ? "espera" : "ok",
        titulo: `${contagem(lote.criadas, "empresa criada", "empresas criadas")}`,
        descricao: `${contagem(lote.certificados, "certificado", "certificados")} · ${numero(lote.ja_existiam)} já existiam · ${numero(lote.erros)} com erro`,
      });
      aoImportar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "importar o lote"));
    } finally {
      setEnviando(false);
    }
  }

  /**
   * Uma consulta por CNPJ que ainda não tem nome: primeiro o cadastro do
   * escritório no Acessórias, depois a Receita. Sem isso, o lote que importou
   * o nome da cadeia ("ICP-Brasil") ficararia assim para sempre.
   */
  async function completarNomes() {
    setCompletando(true);
    try {
      const reparo = await api.completarCadastrosEmpresas({ reconsultar: true });
      avisar(
        reparo.corrigidas > 0
          ? {
              tom: "ok",
              titulo: `${contagem(reparo.corrigidas, "razão social corrigida", "razões sociais corrigidas")}`,
              descricao: `${numero(reparo.uf_completada)} UF completadas · ${numero(reparo.sem_fonte)} sem cadastro em nenhuma fonte`,
            }
          : {
              tom: "espera",
              titulo: "Nenhum nome encontrado",
              descricao:
                "Essas empresas não estão no Acessórias e a consulta pública não respondeu. Inclua a razão social na planilha de apoio e importe de novo.",
            }
      );
      if (reparo.corrigidas > 0 || reparo.uf_completada > 0) aoImportar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "completar os cadastros"));
    } finally {
      setCompletando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={fechar}
      titulo="Importar empresas em massa"
      descricao="Envie a pasta de certificados A1 (.pfx/.p12). O CNPJ e a razão social saem do certificado; a UF é consultada automaticamente."
      largura="larga"
      rodape={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-tinta-suave">
            {resultado
              ? "Lote processado — revise os itens antes de fechar."
              : senhasNaPlanilha
                ? "A planilha de apoio será usada para abrir os certificados deste lote."
                : "As senhas são identificadas automaticamente. Se algum arquivo não abrir, anexe uma planilha de apoio e tente de novo."}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={fechar}>
              {resultado ? "Concluir" : "Cancelar"}
            </Botao>
            {resultado ? null : (
              <Botao variante="primaria" onClick={enviar} carregando={enviando} disabled={!podeEnviar} title={podeEnviar ? undefined : motivoBloqueio}>
                Importar lote
              </Botao>
            )}
          </div>
        </div>
      }
    >
      {resultado ? (
        <ResultadoLote
          resultado={resultado}
          planilhasAnexadas={planilhas.length}
          aoCompletar={completarNomes}
          completando={completando}
        />
      ) : (
        <Formulario aoEnviar={enviar} ocupado={enviando} className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 rounded-controle border border-borda-controle p-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-tinta">Pasta dos certificados no computador</p>
              <p className="mt-0.5 text-xs leading-5 text-tinta-suave">
                Um clique na pasta e pronto: só os <span className="font-medium">.pfx/.p12</span> são lidos — o resto
                da pasta é ignorado. O CNPJ e a razão social saem do próprio certificado.
              </p>
              {arquivosIgnorados > 0 ? (
                <p className="mt-1 text-2xs text-tinta-fraca">
                  {plural(arquivosIgnorados, "arquivo ignorado — não é certificado", "arquivos ignorados — não são certificados")}.
                </p>
              ) : null}
              {substituidosDaPasta > 0 ? (
                <p className="mt-1 text-2xs text-tinta-fraca">
                  {plural(substituidosDaPasta, "versão antiga ficou de fora", "versões antigas ficaram de fora")} — de cada
                  CNPJ, só a versão mais recente é enviada.
                </p>
              ) : null}
              {acimaDoLote ? (
                <ErroDoCampo className="mt-1">{motivoBloqueio}</ErroDoCampo>
              ) : null}
            </div>
            <input
              ref={pastaRef}
              type="file"
              className="hidden"
              {...ATRIBUTOS_SELETOR_DE_PASTA}
              onChange={(evento) => receberPasta(evento.target.files)}
            />
            <Botao
              variante="secundaria"
              tamanho="sm"
              onClick={() => pastaRef.current?.click()}
              iconeEsquerda={<Icone nome="pasta" className="h-4 w-4" />}
            >
              Escolher pasta
            </Botao>
          </div>

          <CampoArquivo
            rotulo="Ou arquivos individuais"
            aceita=".p12,.pfx"
            multiplo
            arquivos={certificados}
            aoMudar={setCertificados}
            descricao="Arraste aqui se preferir. Um arquivo por empresa."
          />
          <CampoArquivo
            rotulo="Planilha de apoio (opcional)"
            aceita=".xlsx,.xlsm,.xls,.csv,.txt"
            multiplo
            arquivos={planilhas}
            aoMudar={setPlanilhas}
            descricao="Anexe a planilha que o escritório já tem: valem cnpj;senha, razao_social;cnpj_cpf;uf;senha e o inventário de A1 arquivo;cnpj;emissor;senha;validade — com ou sem linha de título. Cada certificado é amarrado à sua linha pelo CNPJ que está no nome do arquivo. A UF só é usada como apoio se a consulta pública não a encontrar."
          />
          {erro ? (
            <Aviso tom="erro" compacto urgente>
              {erro}
            </Aviso>
          ) : null}
        </Formulario>
      )}
    </Modal>
  );
}

function ResultadoLote({
  resultado,
  planilhasAnexadas = 0,
  aoCompletar,
  completando = false,
}: {
  resultado: LoteEmpresasResposta;
  planilhasAnexadas?: number;
  aoCompletar?: () => void;
  completando?: boolean;
}) {
  const linhasDaPlanilha = resultado.linhas_da_planilha ?? 0;
  const senhasDaPlanilha = resultado.senhas_da_planilha ?? 0;
  const semNome = resultado.empresas_sem_nome ?? 0;
  return (
    <div className="space-y-4">
      <Cartao densidade="compacta" className="border-0 bg-fundo-afundado">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-5">
          <Dado destaque rotulo="Processados" valor={numero(resultado.total)} />
          <Dado destaque rotulo="Criadas" valor={numero(resultado.criadas)} tom="ok" />
          <Dado destaque rotulo="Certificados" valor={numero(resultado.certificados)} />
          <Dado destaque rotulo="Já existiam" valor={numero(resultado.ja_existiam)} />
          <Dado destaque rotulo="Com erro" valor={numero(resultado.erros)} tom={resultado.erros > 0 ? "erro" : undefined} />
        </dl>
        {semNome > 0 ? (
          <Aviso tom="espera" compacto className="mt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {contagem(semNome, "empresa entrou sem razão social", "empresas entraram sem razão social")} — nem o
                certificado, nem a planilha e nem o Acessórias disseram o nome dela. Elas entram listadas como
                “Empresa &lt;CNPJ&gt;”.
              </span>
              {aoCompletar ? (
                <Botao
                  variante="secundaria"
                  tamanho="sm"
                  onClick={aoCompletar}
                  carregando={completando}
                  title="Consulta o cadastro do escritório no Acessórias e, para o que não está lá, a Receita"
                >
                  Completar nomes agora
                </Botao>
              ) : null}
            </div>
          </Aviso>
        ) : null}
        {planilhasAnexadas > 0 ? (
          linhasDaPlanilha === 0 ? (
            <Aviso tom="erro" compacto urgente className="mt-3">
              A planilha anexada não rendeu nenhuma linha. Ela precisa do CNPJ (ou do nome do .pfx) e da senha de
              cada certificado — confira as colunas e importe de novo.
            </Aviso>
          ) : (
            <p className="mt-3 border-t border-traco pt-2 text-2xs leading-5 text-tinta-suave">
              Planilha de apoio: {numero(linhasDaPlanilha)}{" "}
              {plural(linhasDaPlanilha, "linha lida", "linhas lidas")} · {numero(senhasDaPlanilha)}{" "}
              {plural(senhasDaPlanilha, "com senha", "com senha")}.
            </p>
          )
        ) : null}
      </Cartao>

      <div className="caixa-tabela max-h-80">
        <table className="tabela-dados">
          <caption className="sr-only">Itens processados no lote</caption>
          <thead>
            <tr>
              <th scope="col">Origem</th>
              <th scope="col">Empresa</th>
              <th scope="col">Situação</th>
              <th scope="col">Mensagem</th>
            </tr>
          </thead>
          <tbody>
            {resultado.itens.map((item: ItemLoteEmpresas, indice) => {
              const vencido = item.validade ? new Date(item.validade).getTime() < Date.now() : false;
              const tomItem =
                item.status === "erro"
                  ? "erro"
                  : item.status === "substituido" || item.status === "ja_existia"
                    ? "neutro"
                    : vencido
                      ? "espera"
                      : "ok";
              return (
              <tr key={`${item.cnpj_cpf}-${indice}`}>
                <td className="text-xs text-tinta-suave">{item.origem}</td>
                <th scope="row">
                  <span className="block truncate text-tinta">{item.razao_social || "—"}</span>
                  <Cnpj valor={item.cnpj_cpf} copiar={false} className="text-xs text-tinta-suave" />
                </th>
                <td>
                  <Etiqueta tom={tomItem} titulo={vencido && item.status !== "erro" ? "Certificado vencido" : undefined}>
                    {ROTULO_STATUS_LOTE[item.status] ?? item.status}
                  </Etiqueta>
                </td>
                <td className="max-w-0">
                  <span className="block truncate text-xs text-tinta-suave" title={item.mensagem}>
                    {item.mensagem || "—"}
                  </span>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

