"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { dataCurta, numero, plural } from "@/lib/format";
import { estadoDoCertificado } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Busca, Entrada } from "@/components/ui/Campo";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { Combobox } from "@/components/ui/Combobox";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, DataHora, Truncado } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Modal } from "@/components/ui/Modal";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import type { CertificadoPainel } from "@/lib/types";

type FiltroCertificado = "" | "validos" | "vencendo" | "vencidos" | "sem";

const FILTROS: Array<{ valor: FiltroCertificado; rotulo: string }> = [
  { valor: "", rotulo: "Todos" },
  { valor: "validos", rotulo: "Válidos" },
  { valor: "vencendo", rotulo: "Vencendo em 30 dias" },
  { valor: "vencidos", rotulo: "Vencidos" },
  { valor: "sem", rotulo: "Sem certificado" },
];

/**
 * Centro de certificados A1.
 *
 * A pergunta desta tela é "qual empresa para de capturar amanhã?". Por isso a
 * ordenação padrão é validade crescente, o filtro de vencidos vem pronto no link
 * dos alertas (`?filtro=vencidos`) e a senha nunca aparece: ela é usada uma vez,
 * no envio, e o servidor guarda só o arquivo cifrado.
 */
export function Certificados() {
  const { definir, ler } = useUrlEstado();
  const busca = useBuscaUrl();
  const { somenteLeitura } = useSessao();

  const filtro = (FILTROS.some((opcao) => opcao.valor === ler("filtro")) ? ler("filtro") : "") as FiltroCertificado;
  const ordem = ler("ordem") || "validade";
  const sentido = ler("sentido") === "desc" ? "desc" : "asc";

  const [envioAberto, setEnvioAberto] = useState(false);
  const [empresaAlvo, setEmpresaAlvo] = useState<number | null>(null);

  const painel = useRecurso(() => api.painelCertificados(), []);
  const empresas = useRecurso(() => api.listarEmpresas(), []);
  useSinalizarAtualizacao(painel.atualizando);

  const linhas = useMemo<CertificadoPainel[]>(() => {
    const porEmpresa = new Map<number, CertificadoPainel>();
    for (const item of painel.dados ?? []) porEmpresa.set(item.empresa_id, item);
    const base = (empresas.dados ?? []).map<CertificadoPainel>((empresa) => {
      const encontrado = porEmpresa.get(empresa.id);
      if (encontrado) return { ...encontrado, razao_social: empresa.razao_social, cnpj_cpf: encontrado.cnpj_cpf || empresa.cnpj_cpf };
      return {
        empresa_id: empresa.id,
        razao_social: empresa.razao_social,
        cnpj_cpf: empresa.cnpj_cpf,
        tem_certificado: false,
        validade: null,
        dias_para_vencer: null,
        vencido: false,
        vence_em_breve: false,
        ultima_utilizacao_em: null,
        ultima_validacao_em: null,
        ultimo_erro: null,
      };
    });
    // Empresas com certificado mas sem cadastro visível (caso raro) ainda contam.
    for (const item of painel.dados ?? []) {
      if (!base.some((linha) => linha.empresa_id === item.empresa_id)) base.push(item);
    }
    return base;
  }, [empresas.dados, painel.dados]);

  const contagem = useMemo(
    () => ({
      validos: linhas.filter((linha) => linha.tem_certificado && !linha.vencido && !linha.vence_em_breve).length,
      vencendo: linhas.filter((linha) => linha.vence_em_breve).length,
      vencidos: linhas.filter((linha) => linha.vencido).length,
      sem: linhas.filter((linha) => !linha.tem_certificado).length,
    }),
    [linhas]
  );

  const filtradas = useMemo(() => {
    const termo = busca.valor.trim().toLocaleLowerCase("pt-BR");
    const digitos = termo.replace(/\D/g, "");
    const resultado = linhas.filter((linha) => {
      if (termo) {
        const casaTexto = linha.razao_social.toLocaleLowerCase("pt-BR").includes(termo);
        const casaCnpj = digitos.length >= 2 && (linha.cnpj_cpf ?? "").replace(/\D/g, "").includes(digitos);
        if (!casaTexto && !casaCnpj) return false;
      }
      switch (filtro) {
        case "validos":
          return linha.tem_certificado && !linha.vencido && !linha.vence_em_breve;
        case "vencendo":
          return linha.vence_em_breve;
        case "vencidos":
          return linha.vencido;
        case "sem":
          return !linha.tem_certificado;
        default:
          return true;
      }
    });
    const fator = sentido === "asc" ? 1 : -1;
    return [...resultado].sort((a, b) => fator * compararCertificados(a, b, ordem));
  }, [busca.valor, filtro, linhas, ordem, sentido]);

  const colunas = useMemo<Array<ColunaTabela<CertificadoPainel>>>(
    () => [
      {
        id: "empresa",
        cabecalho: "Empresa",
        largura: "min-w-56",
        fixa: true,
        ordenavel: true,
        celula: (linha) => (
          <Link href={`/dashboard/empresa?id=${linha.empresa_id}&aba=certificado`} className="block truncate font-medium text-tinta underline-offset-4 hover:text-acento hover:underline" title={linha.razao_social}>
            {linha.razao_social}
          </Link>
        ),
      },
      { id: "cnpj", cabecalho: "CNPJ", celula: (linha) => <Cnpj valor={linha.cnpj_cpf} /> },
      {
        id: "situacao",
        cabecalho: "Situação",
        ordenavel: true,
        celula: (linha) => <IndicadorEstado {...estadoDoCertificado(linha)} titulo={linha.validade ? `Validade ${dataCurta(linha.validade)}` : undefined} />,
      },
      {
        id: "validade",
        cabecalho: "Validade",
        alinhamento: "direita",
        numerica: true,
        ordenavel: true,
        celula: (linha) => (linha.validade ? <span className="nums">{dataCurta(linha.validade)}</span> : <span className="text-tinta-fraca">—</span>),
      },
      {
        id: "dias",
        cabecalho: "Dias",
        alinhamento: "direita",
        numerica: true,
        ordenavel: true,
        dica: "Negativo = vencido há N dias",
        celula: (linha) =>
          linha.dias_para_vencer === null ? (
            <span className="text-tinta-fraca">—</span>
          ) : (
            <span className={linha.vencido ? "text-erro" : linha.vence_em_breve ? "text-espera" : "text-tinta"}>{numero(linha.dias_para_vencer)}</span>
          ),
      },
      {
        id: "utilizacao",
        cabecalho: "Última utilização",
        dica: "Quando o certificado foi de fato usado numa consulta à SEFAZ",
        celula: (linha) => (linha.ultima_utilizacao_em ? <DataHora iso={linha.ultima_utilizacao_em} /> : <span className="text-tinta-fraca">nunca usado</span>),
      },
      {
        id: "validacao",
        cabecalho: "Última validação",
        ocultaPorPadrao: true,
        celula: (linha) => (linha.ultima_validacao_em ? <DataHora iso={linha.ultima_validacao_em} /> : <span className="text-tinta-fraca">—</span>),
      },
      {
        id: "erro",
        cabecalho: "Último erro de autenticação",
        largura: "min-w-48",
        celula: (linha) =>
          linha.ultimo_erro ? (
            <Truncado texto={linha.ultimo_erro} className="text-erro" titulo={linha.ultimo_erro} />
          ) : (
            <span className="text-tinta-fraca">nenhum</span>
          ),
      },
      {
        id: "acoes",
        cabecalho: "",
        alinhamento: "direita",
        celula: (linha) => (
          <Botao
            variante="sutil"
            tamanho="sm"
            disabled={somenteLeitura}
            title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : linha.tem_certificado ? "Substituir o certificado desta empresa" : "Enviar certificado"}
            onClick={() => {
              setEmpresaAlvo(linha.empresa_id);
              setEnvioAberto(true);
            }}
          >
            {linha.tem_certificado ? "Substituir" : "Enviar"}
          </Botao>
        ),
      },
    ],
    [somenteLeitura]
  );

  const indicadores: KpiProps[] = [
    { rotulo: "Válidos", valor: numero(contagem.validos), tom: "ok", href: "/dashboard/certificados?filtro=validos", carregando: painel.carregando },
    { rotulo: "Vencendo em 30 dias", valor: numero(contagem.vencendo), tom: contagem.vencendo > 0 ? "espera" : "neutro", href: "/dashboard/certificados?filtro=vencendo", carregando: painel.carregando },
    { rotulo: "Vencidos", valor: numero(contagem.vencidos), tom: contagem.vencidos > 0 ? "erro" : "neutro", href: "/dashboard/certificados?filtro=vencidos", carregando: painel.carregando, dica: "Empresa com certificado vencido para de capturar documentos." },
    { rotulo: "Sem certificado", valor: numero(contagem.sem), tom: contagem.sem > 0 ? "erro" : "neutro", href: "/dashboard/certificados?filtro=sem", carregando: painel.carregando },
  ];

  const vencidos = linhas.filter((linha) => linha.vencido || !linha.tem_certificado);

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Certificados"
        descricao="Validade, uso real e falhas de autenticação de cada A1. Sem certificado válido não há captura."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={painel.atualizar} carregando={painel.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            <Botao
              variante="primaria"
              onClick={() => {
                setEmpresaAlvo(null);
                setEnvioAberto(true);
              }}
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="certificado" className="h-4 w-4" />}
            >
              Enviar certificado
            </Botao>
          </div>
        }
      />

      {vencidos.length > 0 ? (
        <Aviso tom={contagem.vencidos > 0 ? "erro" : "espera"} icone="certificado" titulo={`${numero(vencidos.length)} ${plural(vencidos.length, "empresa está", "empresas estão")} sem captura garantida`}>
          Certificado vencido ou ausente faz a SEFAZ recusar a consulta: o cursor (NSU) para e os documentos deixam de chegar. Substitua o A1 — a
          varredura automática retoma sozinha na próxima janela.
        </Aviso>
      ) : null}

      <GradeKpis itens={indicadores} colunas={4} rotulo="Situação dos certificados" />

      <Tabela
        linhas={filtradas}
        colunas={colunas}
        chaveDaLinha={(linha) => linha.empresa_id}
        legenda="Certificados A1 por empresa"
        ordenacao={{ coluna: ordem, direcao: sentido }}
        aoOrdenar={(proxima) => definir({ ordem: proxima?.coluna ?? null, sentido: proxima?.direcao ?? null })}
        virtualizar
        estados={{
          carregando: painel.carregando && empresas.carregando,
          erro: painel.erro ?? empresas.erro,
          aoTentarNovamente: painel.atualizar,
          vazioTitulo: "Nenhum certificado neste recorte",
          vazioInstrucao: "Troque o filtro ou cadastre a empresa antes de enviar o A1.",
          vazioIcone: "certificado",
          filtroAtivo: Boolean(filtro || busca.valor.trim()),
          aoLimparFiltro: () => {
            definir({ filtro: null, busca: null });
            busca.aoMudar("");
          },
        }}
        ferramentas={
          <div className="flex flex-wrap items-end gap-2">
            <Busca rotulo="Buscar certificado" placeholder="Empresa ou CNPJ" valor={busca.valor} aoMudar={busca.aoMudar} className="min-w-64 flex-1" />
            <div className="flex flex-wrap items-center gap-1">
              {FILTROS.map((opcao) => (
                <button
                  key={opcao.valor}
                  type="button"
                  onClick={() => definir({ filtro: opcao.valor || null })}
                  aria-pressed={filtro === opcao.valor}
                  className={
                    filtro === opcao.valor
                      ? "inline-flex h-9 items-center rounded-controle border border-acento bg-acento-tenue px-2.5 text-xs font-medium text-acento"
                      : "inline-flex h-9 items-center rounded-controle border border-borda-controle bg-superficie px-2.5 text-xs text-tinta-suave transition-colors duration-120 hover:border-tinta-suave hover:text-tinta"
                  }
                >
                  {opcao.rotulo}
                </button>
              ))}
            </div>
          </div>
        }
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {numero(filtradas.length)} {plural(filtradas.length, "empresa", "empresas")} · ordenadas por validade (a mais urgente primeiro)
            {painel.ultimaAtualizacao ? <span className="ml-2 text-tinta-fraca">· consultado <DataHora iso={new Date(painel.ultimaAtualizacao).toISOString()} /></span> : null}
          </p>
        }
      />

      <ModalEnvioCertificado
        aberto={envioAberto}
        aoFechar={() => setEnvioAberto(false)}
        empresaInicial={empresaAlvo}
        empresas={(empresas.dados ?? []).map((empresa) => ({ valor: String(empresa.id), rotulo: empresa.razao_social, descricao: empresa.cnpj_cpf }))}
        aoInstalar={() => {
          painel.atualizar();
          empresas.atualizar();
        }}
      />
    </div>
  );
}

function compararCertificados(a: CertificadoPainel, b: CertificadoPainel, coluna: string): number {
  switch (coluna) {
    case "empresa":
      return a.razao_social.localeCompare(b.razao_social, "pt-BR");
    case "situacao":
      return (a.dias_para_vencer ?? Number.MAX_SAFE_INTEGER) - (b.dias_para_vencer ?? Number.MAX_SAFE_INTEGER);
    case "validade":
      return (a.validade ?? "9999").localeCompare(b.validade ?? "9999");
    case "dias":
      return (a.dias_para_vencer ?? Number.MAX_SAFE_INTEGER) - (b.dias_para_vencer ?? Number.MAX_SAFE_INTEGER);
    default:
      return 0;
  }
}

function ModalEnvioCertificado({
  aberto,
  aoFechar,
  empresaInicial,
  empresas,
  aoInstalar,
}: {
  aberto: boolean;
  aoFechar: () => void;
  empresaInicial: number | null;
  empresas: Array<{ valor: string; rotulo: string; descricao?: string }>;
  aoInstalar: () => void;
}) {
  const { avisar } = useToast();
  const [empresa, setEmpresa] = useState(empresaInicial ? String(empresaInicial) : "");
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [senha, setSenha] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Reabrir para outra empresa não pode manter a seleção anterior.
  useEffect(() => {
    if (aberto) setEmpresa(empresaInicial ? String(empresaInicial) : "");
  }, [aberto, empresaInicial]);

  function fechar() {
    setArquivos([]);
    setSenha("");
    setErro(null);
    aoFechar();
  }

  async function instalar() {
    const arquivo = arquivos[0];
    const empresaId = Number(empresa);
    if (!empresaId) {
      setErro("Escolha a empresa que vai receber o certificado.");
      return;
    }
    if (!arquivo) {
      setErro("Selecione o arquivo .p12 ou .pfx.");
      return;
    }
    if (!senha) {
      setErro("Informe a senha do certificado — sem ela o servidor não consegue abrir o arquivo.");
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const criado = await api.enviarCertificado(empresaId, senha, arquivo);
      avisar({ tom: "ok", titulo: "Certificado instalado", descricao: `Válido até ${dataCurta(criado.validade)}` });
      aoInstalar();
      fechar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "instalar o certificado"));
    } finally {
      setEnviando(false);
    }
  }

  const podeInstalar = Boolean(empresa) && arquivos.length > 0 && senha.length > 0;

  return (
    <Modal
      aberto={aberto}
      aoFechar={fechar}
      titulo="Enviar certificado A1"
      descricao="O arquivo é cifrado no servidor. A senha é usada uma vez, para abrir o .p12, e nunca volta ao navegador."
      largura="media"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={fechar}>
            Cancelar
          </Botao>
          <Botao variante="primaria" onClick={instalar} carregando={enviando} disabled={!podeInstalar} title={podeInstalar ? undefined : "Preencha empresa, arquivo e senha"}>
            Instalar certificado
          </Botao>
        </div>
      }
    >
      <div className="space-y-4">
        <div>
          <p className="mb-1.5 text-xs font-medium text-tinta">
            Empresa <span className="text-erro">*</span>
          </p>
          <Combobox
            rotulo="Empresa"
            opcoes={empresas}
            valor={empresa}
            aoMudar={setEmpresa}
            placeholder="Buscar por razão social ou CNPJ"
            vazio="Nenhuma empresa cadastrada"
            permiteLimpar
          />
        </div>
        <CampoArquivo
          rotulo="Arquivo do certificado"
          obrigatorio
          aceita=".p12,.pfx"
          arquivos={arquivos}
          aoMudar={(lista) => setArquivos(lista.slice(0, 1))}
          descricao="Substitui o certificado atual da empresa escolhida."
        />
        <Entrada
          rotulo="Senha do certificado"
          obrigatorio
          type="password"
          autoComplete="off"
          value={senha}
          onChange={(evento) => setSenha(evento.target.value)}
          descricao="Nenhuma tela exibe esta senha depois de enviada."
        />
        {erro ? (
          <p role="alert" className="flex items-start gap-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
            <Icone nome="alerta" className="mt-1 h-4 w-4 flex-none" />
            <span>{erro}</span>
          </p>
        ) : null}
        {empresa ? (
          <p className="text-xs text-tinta-suave">
            Selecionada: <span className="text-tinta">{empresas.find((opcao) => opcao.valor === empresa)?.rotulo ?? "—"}</span>
            <Etiqueta tom="neutro" className="ml-2">
              um certificado por empresa
            </Etiqueta>
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
