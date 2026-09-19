"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { dataCurta, formatarCnpjCpf, numero, plural, somenteDigitos } from "@/lib/format";
import { estadoDaSincronizacao, estadoDoCertificado, type EstadoVisual } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
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
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Busca, Entrada, Selecao } from "@/components/ui/Campo";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { Dado } from "@/components/ui/Dado";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, DataHora, ValorMoeda } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
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
  const sentido = ler("sentido") === "asc" ? "asc" : "desc";

  const [densidade, setDensidade] = usePreferencia<DensidadeTabela>("empresas-densidade", "confortavel");
  const [colunasVisiveis, setColunasVisiveis] = usePreferencia<string[] | null>("empresas-colunas", null);
  const [novaAberta, setNovaAberta] = useState(false);
  const [loteAberto, setLoteAberto] = useState(false);

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
      { id: "cnpj", cabecalho: "CNPJ", ordenavel: true, celula: (linha) => <Cnpj valor={linha.empresa.cnpj_cpf} /> },
      { id: "uf", cabecalho: "UF", ordenavel: true, celula: (linha) => <span className="nums text-tinta-suave">{linha.empresa.uf || "—"}</span> },
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
        ordenavel: true,
        celula: (linha) =>
          linha.sincronismo ? (
            <IndicadorEstado {...linha.sincronismo} detalhe={linha.pendencia > 0 ? <span className="nums">· {numero(linha.pendencia)} pendentes</span> : undefined} />
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
        titulo="Empresas"
        descricao="Cadastro, certificado A1 e volume capturado de cada CNPJ do escritório."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={recarregar} carregando={empresas.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            <Botao
              variante="secundaria"
              onClick={() => setLoteAberto(true)}
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="arrastar" className="h-4 w-4" />}
            >
              Importar em massa
            </Botao>
            <Botao
              variante="primaria"
              onClick={() => setNovaAberta(true)}
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="adicionar" className="h-4 w-4" />}
            >
              Nova empresa
            </Botao>
          </div>
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
        aoMudarDensidade={setDensidade}
        colunasVisiveis={colunasVisiveis ?? undefined}
        aoMudarColunas={(ids) => setColunasVisiveis(ids)}
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
          <div className="flex flex-wrap items-end gap-2">
            <Busca rotulo="Buscar empresa" placeholder="Razão social ou CNPJ" valor={busca.valor} aoMudar={busca.aoMudar} className="min-w-64 flex-1" />
            <Selecao
              rotulo="Situação"
              className="w-60"
              value={situacao}
              onChange={(evento) => definir({ situacao: evento.target.value || null })}
              opcoes={SITUACOES.map((opcao) => ({ valor: opcao.valor, rotulo: opcao.rotulo }))}
            />
          </div>
        }
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {numero(filtradas.length)} {plural(filtradas.length, "empresa", "empresas")} · {numero(linhas.filter((linha) => !linha.certificado?.tem_certificado).length)} sem certificado ·{" "}
            {numero(linhas.filter((linha) => linha.pendencia > 0).length)} com pendência
          </p>
        }
      />

      <ModalNovaEmpresa aberto={novaAberta} aoFechar={() => setNovaAberta(false)} aoCriar={recarregar} />
      <ModalImportacaoLote aberto={loteAberto} aoFechar={() => setLoteAberto(false)} aoImportar={recarregar} />
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
    const digitos = somenteDigitos(cnpj);
    if (digitos.length !== 14 && digitos.length !== 11) {
      setErrosCampo((atual) => ({ ...atual, cnpj: "Informe um CNPJ (14 dígitos) ou CPF (11 dígitos) para consultar." }));
      return;
    }
    setConsultando(true);
    setNota(null);
    try {
      const consulta = await api.consultarCnpj(digitos);
      if (consulta.encontrado) {
        setRazao(consulta.razao_social || razao);
        setUf(consulta.uf || uf);
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
    const digitos = somenteDigitos(cnpj);
    const proximosErros: typeof errosCampo = {};
    if (!razao.trim()) proximosErros.razao = "Informe a razão social como consta no certificado.";
    if (digitos.length !== 14 && digitos.length !== 11) proximosErros.cnpj = "CNPJ tem 14 dígitos; CPF, 11.";
    setErrosCampo(proximosErros);
    if (Object.keys(proximosErros).length > 0) return;

    setEnviando(true);
    setErro(null);
    try {
      const criada = await api.criarEmpresa(razao.trim(), digitos, uf || undefined);
      avisar({ tom: "ok", titulo: "Empresa cadastrada", descricao: `${criada.razao_social} · ${formatarCnpjCpf(criada.cnpj_cpf)}` });
      aoCriar();
      fechar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "cadastrar a empresa"));
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
      <div className="space-y-4">
        <Entrada
          rotulo="CNPJ ou CPF"
          obrigatorio
          value={cnpj}
          onChange={(evento) => setCnpj(evento.target.value)}
          placeholder="00.000.000/0000-00"
          mono
          erro={errosCampo.cnpj ?? null}
          nota={nota}
          inputMode="numeric"
          autoComplete="off"
          acaoRotulo={
            <button
              type="button"
              onClick={consultarCnpj}
              disabled={consultando}
              className="inline-flex items-center gap-1 rounded-badge px-1.5 py-0.5 text-xs font-medium text-acento underline-offset-4 hover:underline disabled:opacity-50"
            >
              {consultando ? "Consultando…" : "Consultar CNPJ"}
            </button>
          }
        />
        <Entrada
          rotulo="Razão social"
          obrigatorio
          value={razao}
          onChange={(evento) => setRazao(evento.target.value)}
          erro={errosCampo.razao ?? null}
          descricao="Como consta no certificado A1 — é o nome que aparece nas listas."
        />
        <Selecao
          rotulo="UF"
          value={uf}
          onChange={(evento) => setUf(evento.target.value)}
          descricao="Opcional: ajuda a localizar a empresa e valida o município do emitente."
          opcoes={[{ valor: "", rotulo: "Não informar" }, ...UFS.map((item) => ({ valor: item.sigla, rotulo: `${item.sigla} · ${item.nome}` }))]}
        />
        {erro ? (
          <p role="alert" className="rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
            {erro}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

function ModalImportacaoLote({ aberto, aoFechar, aoImportar }: { aberto: boolean; aoFechar: () => void; aoImportar: () => void }) {
  const { avisar } = useToast();
  const [certificados, setCertificados] = useState<File[]>([]);
  const [planilhas, setPlanilhas] = useState<File[]>([]);
  const [senha, setSenha] = useState("");
  const [ufPadrao, setUfPadrao] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<LoteEmpresasResposta | null>(null);

  const podeEnviar = certificados.length > 0 && senha.trim().length > 0 && ufPadrao !== "";

  function limpar() {
    setCertificados([]);
    setPlanilhas([]);
    setSenha("");
    setUfPadrao("");
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
      const lote = await api.importarEmpresasEmMassa(certificados, planilhas[0] ?? null, senha.trim(), ufPadrao);
      setResultado(lote);
      avisar({
        tom: lote.erros > 0 ? "espera" : "ok",
        titulo: `${numero(lote.criadas)} ${plural(lote.criadas, "empresa criada", "empresas criadas")}`,
        descricao: `${numero(lote.certificados)} ${plural(lote.certificados, "certificado", "certificados")} · ${numero(lote.ja_existiam)} já existiam · ${numero(lote.erros)} com erro`,
      });
      aoImportar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "importar o lote"));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={fechar}
      titulo="Importar empresas em massa"
      descricao="Envie os certificados A1 (.p12/.pfx) do escritório e, se quiser, uma planilha com razão social, CNPJ e UF."
      largura="larga"
      rodape={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-tinta-suave">
            {resultado ? "Lote processado — revise os itens antes de fechar." : "A senha vale para todos os arquivos deste lote."}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={fechar}>
              {resultado ? "Concluir" : "Cancelar"}
            </Botao>
            {resultado ? null : (
              <Botao variante="primaria" onClick={enviar} carregando={enviando} disabled={!podeEnviar} title={podeEnviar ? undefined : "Envie ao menos um certificado, a senha e a UF padrão"}>
                Importar lote
              </Botao>
            )}
          </div>
        </div>
      }
    >
      {resultado ? (
        <ResultadoLote resultado={resultado} />
      ) : (
        <div className="space-y-4">
          <CampoArquivo
            rotulo="Certificados A1"
            obrigatorio
            aceita=".p12,.pfx"
            multiplo
            arquivos={certificados}
            aoMudar={setCertificados}
            descricao="Um arquivo por empresa. O CNPJ sai do próprio certificado."
          />
          <CampoArquivo
            rotulo="Planilha de empresas (opcional)"
            aceita=".csv,.xlsx,.xls"
            arquivos={planilhas}
            aoMudar={(arquivos) => setPlanilhas(arquivos.slice(0, 1))}
            descricao="Colunas aceitas: razao_social, cnpj_cpf, uf. Complementa o que o certificado não traz."
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Entrada
              rotulo="Senha dos certificados"
              obrigatorio
              type="password"
              autoComplete="off"
              value={senha}
              onChange={(evento) => setSenha(evento.target.value)}
              descricao="Usada só para abrir os arquivos; não é guardada no navegador."
            />
            <Selecao
              rotulo="UF padrão"
              obrigatorio
              value={ufPadrao}
              onChange={(evento) => setUfPadrao(evento.target.value)}
              descricao="Aplicada às empresas sem UF na planilha."
              opcoes={[{ valor: "", rotulo: "Selecione a UF" }, ...UFS.map((item) => ({ valor: item.sigla, rotulo: `${item.sigla} · ${item.nome}` }))]}
            />
          </div>
          {erro ? (
            <p role="alert" className="rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
              {erro}
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

function ResultadoLote({ resultado }: { resultado: LoteEmpresasResposta }) {
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
      </Cartao>

      <div className="rolagem-fina max-h-80 overflow-y-auto rounded-cartao border border-traco">
        <table className="w-full text-sm">
          <caption className="sr-only">Itens processados no lote</caption>
          <thead className="sticky top-0 bg-superficie-alta">
            <tr className="border-b border-traco text-left text-2xs uppercase tracking-[.04em] text-tinta-suave">
              <th scope="col" className="px-3 py-2 font-medium">
                Origem
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Empresa
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Situação
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Mensagem
              </th>
            </tr>
          </thead>
          <tbody>
            {resultado.itens.map((item: ItemLoteEmpresas, indice) => (
              <tr key={`${item.cnpj_cpf}-${indice}`} className="border-b border-traco last:border-0">
                <td className="px-3 py-2 text-xs text-tinta-suave">{item.origem}</td>
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <span className="block truncate text-tinta">{item.razao_social || "—"}</span>
                  <Cnpj valor={item.cnpj_cpf} copiar={false} className="text-xs text-tinta-suave" />
                </th>
                <td className="px-3 py-2">
                  <Etiqueta tom={item.status === "erro" ? "erro" : item.status === "ja_existia" ? "neutro" : "ok"}>
                    {ROTULO_STATUS_LOTE[item.status] ?? item.status}
                  </Etiqueta>
                </td>
                <td className="max-w-0 px-3 py-2">
                  <span className="block truncate text-xs text-tinta-suave" title={item.mensagem}>
                    {item.mensagem || "—"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

