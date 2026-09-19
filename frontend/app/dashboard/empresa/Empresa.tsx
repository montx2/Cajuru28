"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { dataCurta, dataHora, formatarCnpjCpf, numero, plural, tempoDecorrido } from "@/lib/format";
import { estadoDaExecucao, estadoDaSincronizacao, estadoDoCertificado } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { paraFiltro, rotuloPeriodo } from "@/lib/periodo";
import { UFS } from "@/lib/uf";
import { usePeriodoUrl } from "@/lib/usePeriodoUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { CartaoCertificado } from "@/components/fiscal/CartaoCertificado";
import { PainelDocumento } from "@/components/fiscal/PainelDocumento";
import { ResumoNSU } from "@/components/fiscal/MedidorNSU";
import { SeletorPeriodo } from "@/components/fiscal/SeletorPeriodo";
import { Abas, type Aba } from "@/components/ui/Abas";
import { Alternador, Caixa, Entrada, Selecao } from "@/components/ui/Campo";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { Aviso } from "@/components/ui/Aviso";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { CopiavelMono } from "@/components/ui/CopiavelMono";
import { Dado } from "@/components/ui/Dado";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, DataHora, ValorMoeda } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Modal } from "@/components/ui/Modal";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import {
  ROTULO_TIPO,
  TIPOS,
  type DocumentoDetalhe,
  type DocumentoFiscal,
  type ExecucaoImportacao,
  type JettaxConfiguracaoEmpresa,
  type JettaxExecucao,
  type TipoDocumentoFiscal,
} from "@/lib/types";

const ABAS = ["dados", "certificado", "sincronismo", "documentos", "execucoes", "integracoes"];

/**
 * Detalhe da empresa: tudo que decide a captura dela num lugar só.
 *
 * A aba vem na URL porque os alertas deep-linkam para cá (`?id=7&aba=certificado`)
 * — chegar na aba certa é o que faz o alerta ser resolvível em um clique.
 */
export function Empresa() {
  const router = useRouter();
  const { definir, ler, lerNumero } = useUrlEstado();
  const { somenteLeitura, ehAdmin } = useSessao();
  const { avisar } = useToast();
  const agora = useAgora();
  const { periodo, aoMudar: aoMudarPeriodo, pronto } = usePeriodoUrl();

  const id = lerNumero("id");
  const aba = ABAS.includes(ler("aba")) ? ler("aba") : "dados";
  const documentoAberto = lerNumero("doc") ?? null;

  const [editarAberto, setEditarAberto] = useState(false);
  const [certificadoAberto, setCertificadoAberto] = useState(false);
  const [excluirAberto, setExcluirAberto] = useState(false);
  const [excluindo, setExcluindo] = useState(false);
  const [erroExclusao, setErroExclusao] = useState<string | null>(null);
  const [excluirDocumento, setExcluirDocumento] = useState<DocumentoDetalhe | null>(null);
  const [excluindoDocumento, setExcluindoDocumento] = useState(false);
  const [erroExclusaoDocumento, setErroExclusaoDocumento] = useState<string | null>(null);
  const [completandoXml, setCompletandoXml] = useState(false);

  const empresa = useRecurso(() => (id ? api.obterEmpresa(id) : Promise.reject(new Error("Empresa não informada"))), [id], { automatico: Boolean(id) });
  const certificados = useRecurso(() => api.painelCertificados(), []);
  const sincronizacao = useRecurso(() => (id ? api.sincronizacaoDaEmpresa(id) : Promise.resolve([])), [id], { automatico: Boolean(id) });
  const execucoes = useRecurso(() => (id ? api.listarExecucoes(id) : Promise.resolve([])), [id], { automatico: Boolean(id) });
  const documentos = useRecurso(
    () => (id ? api.listarDocumentos({ empresa_id: id, ...paraFiltro(periodo), limit: 500 }) : Promise.resolve([])),
    [id, periodo.inicio, periodo.fim],
    { automatico: Boolean(id) && pronto && aba === "documentos" }
  );

  const certificado = useMemo(
    () => (certificados.dados ?? []).find((item) => item.empresa_id === id) ?? null,
    [certificados.dados, id]
  );

  useSinalizarAtualizacao(empresa.atualizando || documentos.atualizando || sincronizacao.atualizando);

  function recarregar() {
    empresa.atualizar();
    certificados.atualizar();
    sincronizacao.atualizar();
    execucoes.atualizar();
  }

  async function completarXmls() {
    if (!id) return;
    setCompletandoXml(true);
    try {
      const resultado = await api.completarXmls(id, 50);
      avisar({ tom: resultado.disparado ? "ok" : "espera", titulo: resultado.disparado ? "Busca de XMLs disparada" : "Nada a completar", descricao: resultado.aviso });
      documentos.atualizar();
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível completar os XMLs", descricao: mensagemDoErro(falha, "completar XMLs") });
    } finally {
      setCompletandoXml(false);
    }
  }

  if (!id) {
    return (
      <EstadoVazio
        titulo="Nenhuma empresa selecionada"
        instrucao="Abra uma empresa pela lista para ver certificado, sincronismo e documentos."
        acao={<BotaoLink variante="primaria" href="/dashboard/empresas">Ir para Empresas</BotaoLink>}
        icone="empresa"
      />
    );
  }

  if (empresa.carregando) {
    return (
      <div className="space-y-4" aria-busy="true">
        <EsqueletoBloco linhas={2} />
        <EsqueletoBloco linhas={6} />
      </div>
    );
  }

  if (empresa.erro || !empresa.dados) {
    return <EstadoErro erro={empresa.erro ?? new Error("Empresa não encontrada")} aoTentarNovamente={empresa.atualizar} contexto="carregar a empresa" />;
  }

  const dados = empresa.dados;
  const pendenciaTotal = (sincronizacao.dados ?? []).reduce((soma, estado) => soma + estado.pendencia, 0);
  const documentosNoPeriodo = documentos.dados ?? [];

  const abas: Aba[] = [
    { valor: "dados", rotulo: "Dados", icone: "empresa" },
    {
      valor: "certificado",
      rotulo: "Certificado",
      icone: "certificado",
      contador: certificado && (certificado.vencido || !certificado.tem_certificado) ? 1 : undefined,
    },
    { valor: "sincronismo", rotulo: "Sincronismo", icone: "sincronizar", contador: (sincronizacao.dados ?? []).length || undefined },
    { valor: "documentos", rotulo: "Documentos", icone: "documento", contador: pronto ? documentosNoPeriodo.length || undefined : undefined },
    { valor: "execucoes", rotulo: "Execuções", icone: "execucao", contador: (execucoes.dados ?? []).length || undefined },
    { valor: "integracoes", rotulo: "Integrações", icone: "webhook" },
  ];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        kicker={
          <Link href="/dashboard/empresas" className="inline-flex items-center gap-1 text-xs font-medium text-tinta-suave underline-offset-4 hover:text-acento hover:underline">
            <Icone nome="voltar" className="h-3.5 w-3.5" />
            Empresas
          </Link>
        }
        titulo={dados.razao_social}
        descricao={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Cnpj valor={dados.cnpj_cpf} />
            <span aria-hidden="true">·</span>
            <span>{dados.uf || "UF não informada"}</span>
            <span aria-hidden="true">·</span>
            {dados.ativa ? <IndicadorEstado tom="ok" rotulo="Ativa" icone="verificar-circulo" variante="texto" /> : <IndicadorEstado tom="neutro" rotulo="Inativa" icone="pausa" variante="texto" />}
            {certificado ? <IndicadorEstado {...estadoDoCertificado(certificado)} variante="texto" /> : <IndicadorEstado tom="erro" rotulo="Sem certificado A1" icone="certificado" variante="texto" />}
            {pendenciaTotal > 0 ? (
              <span className="nums text-espera">
                {numero(pendenciaTotal)} {plural(pendenciaTotal, "documento pendente", "documentos pendentes")}
              </span>
            ) : null}
          </span>
        }
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <BotaoLink
              variante="secundaria"
              href={`/dashboard/importacoes?empresa_ids=${dados.id}`}
              indisponivel={somenteLeitura}
              motivo={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}
            >
              Disparar captura
            </BotaoLink>
            <Botao
              variante="secundaria"
              onClick={() => setCertificadoAberto(true)}
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
              iconeEsquerda={<Icone nome="certificado" className="h-4 w-4" />}
            >
              {certificado?.tem_certificado ? "Substituir certificado" : "Enviar certificado"}
            </Botao>
            <Botao variante="primaria" onClick={() => setEditarAberto(true)} disabled={somenteLeitura} title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined} iconeEsquerda={<Icone nome="editar" className="h-4 w-4" />}>
              Editar empresa
            </Botao>
          </div>
        }
      />

      {!dados.ativa ? (
        <Aviso tom="espera" icone="pausa" titulo="Empresa inativa">
          Ela não entra na captura automática e não aparece nas seleções de importação. Reative em “Editar empresa” se voltar a operar.
        </Aviso>
      ) : null}

      <Abas rotulo="Seções da empresa" idBase="aba-empresa" abas={abas} valor={aba} aoMudar={(valor) => definir({ aba: valor })} />

      {aba === "dados" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Cartao titulo="Cadastro">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Dado rotulo="Razão social" valor={dados.razao_social} />
              <Dado rotulo="CNPJ" valor={<Cnpj valor={dados.cnpj_cpf} />} />
              <Dado rotulo="UF" valor={dados.uf || "—"} />
              <Dado rotulo="Código IBGE" valor={dados.codigo_ibge || "—"} mono />
              <Dado rotulo="Inscrição municipal" valor={dados.inscricao_municipal || "—"} mono />
              <Dado rotulo="Cadastrada" valor={<DataHora iso={dados.criado_em} />} />
            </dl>
          </Cartao>

          <Cartao titulo="Captura" descricao="O que esta empresa permite ao robô fazer">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Dado rotulo="Situação" valor={dados.ativa ? "Ativa" : "Inativa"} />
              <Dado rotulo="Sincronismo automático" valor={dados.sincronizar_automaticamente ? "Ligado" : "Desligado"} tom={dados.sincronizar_automaticamente ? undefined : "espera"} />
              <Dado
                rotulo="Tipos sincronizados"
                valor={
                  (dados.quais_tipos_sincronizar ?? "").trim()
                    ? (dados.quais_tipos_sincronizar ?? "")
                        .split(",")
                        .filter(Boolean)
                        .map((tipo) => tipo.trim().toUpperCase())
                        .join(", ")
                    : "Todos os tipos"
                }
              />
              <Dado rotulo="Combinações monitoradas" valor={numero((sincronizacao.dados ?? []).length)} />
            </dl>
            <div className="mt-4 flex flex-wrap gap-2 border-t border-traco pt-3">
              <BotaoLink variante="sutil" tamanho="sm" href={`/dashboard/documentos?empresa=${dados.id}`}>
                Ver documentos
              </BotaoLink>
              <BotaoLink variante="sutil" tamanho="sm" href={`/dashboard/execucoes?empresa=${dados.id}&aba=historico`}>
                Ver execuções
              </BotaoLink>
              {ehAdmin && !somenteLeitura ? (
                <Botao variante="perigo-sutil" tamanho="sm" className="ml-auto" onClick={() => setExcluirAberto(true)} iconeEsquerda={<Icone nome="excluir" className="h-3.5 w-3.5" />}>
                  Excluir empresa
                </Botao>
              ) : null}
            </div>
          </Cartao>
        </div>
      ) : null}

      {aba === "certificado" ? (
        <Cartao
          titulo="Certificado A1"
          descricao="O arquivo fica cifrado no servidor. A senha nunca volta ao navegador nem aparece em tela."
          acoes={
            somenteLeitura ? undefined : (
              <Botao variante="secundaria" tamanho="sm" onClick={() => setCertificadoAberto(true)} iconeEsquerda={<Icone nome="certificado" className="h-4 w-4" />}>
                {certificado?.tem_certificado ? "Substituir" : "Enviar"}
              </Botao>
            )
          }
        >
          <CartaoCertificado
            certificado={
              certificado ?? {
                empresa_id: dados.id,
                razao_social: dados.razao_social,
                tem_certificado: false,
                validade: null,
                dias_para_vencer: null,
                vencido: false,
                vence_em_breve: false,
              }
            }
            aoSubstituir={somenteLeitura ? undefined : () => setCertificadoAberto(true)}
            somenteLeitura={somenteLeitura}
          />
          {certificado && (!certificado.tem_certificado || certificado.vencido) ? (
            <Aviso tom="erro" className="mt-3" titulo="Captura interrompida">
              Sem certificado válido a SEFAZ recusa a consulta: os documentos desta empresa param de chegar e o cursor (NSU) fica para trás. Envie um
              A1 novo para retomar — a varredura volta sozinha na próxima janela.
            </Aviso>
          ) : null}
        </Cartao>
      ) : null}

      {aba === "sincronismo" ? (
        <Cartao titulo="Sincronismo por tipo" descricao="Cursor (NSU), pendência e janela de cada combinação empresa × tipo">
          {sincronizacao.carregando ? (
            <EsqueletoBloco linhas={4} />
          ) : sincronizacao.erro ? (
            <EstadoErro erro={sincronizacao.erro} aoTentarNovamente={sincronizacao.atualizar} contexto="carregar o sincronismo" />
          ) : (sincronizacao.dados ?? []).length === 0 ? (
            <EstadoVazio inline titulo="Sem histórico de sincronismo" instrucao="Dispare a primeira captura para criar o cursor desta empresa." icone="sincronizar" />
          ) : (
            <ul className="divide-y divide-traco">
              {(sincronizacao.dados ?? []).map((estado) => (
                <li key={`${estado.empresa_id}-${estado.tipo}`} className="flex flex-wrap items-center gap-4 py-3">
                  <div className="min-w-32 flex-none">
                    <p className="text-sm font-medium text-tinta-forte">{estado.tipo.toUpperCase()}</p>
                    <IndicadorEstado {...estadoDaSincronizacao(estado, agora)} variante="texto" titulo={estado.motivo_bloqueio ?? undefined} />
                  </div>
                  <ResumoNSU estado={estado} className="min-w-56 flex-1" />
                  <dl className="grid flex-none grid-cols-2 gap-x-6 gap-y-1 text-xs text-tinta-suave">
                    <Dado compacto rotulo="Próxima consulta" valor={estado.proxima_consulta_em ? dataHora(estado.proxima_consulta_em) : "—"} />
                    <Dado compacto rotulo="Última consulta" valor={estado.ultima_consulta_em ? dataHora(estado.ultima_consulta_em) : "—"} />
                    <Dado compacto rotulo="Automático" valor={estado.sincronizar_automaticamente ? "ligado" : "desligado"} />
                    <Dado compacto rotulo="Cota pontual" valor={numero(estado.cota_pontual_disponivel)} />
                  </dl>
                  {estado.risco_documento_fora_da_distribuicao ? (
                    <Etiqueta tom="erro" titulo={estado.dias_sem_varrer !== null ? `${numero(estado.dias_sem_varrer)} dias sem varrer` : undefined}>
                      risco de perda
                    </Etiqueta>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Cartao>
      ) : null}

      {aba === "documentos" ? (
        <Cartao
          titulo={`Documentos · ${rotuloPeriodo(periodo)}`}
          descricao="Acervo capturado desta empresa no período escolhido"
          acoes={
            <Botao variante="secundaria" tamanho="sm" onClick={completarXmls} carregando={completandoXml} disabled={somenteLeitura} title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}>
              Completar XMLs
            </Botao>
          }
        >
          <div className="mb-3">
            <SeletorPeriodo periodo={periodo} aoMudar={aoMudarPeriodo} obrigatorio />
          </div>
          <Tabela
            linhas={documentosNoPeriodo}
            colunas={colunasDocumentos}
            chaveDaLinha={(documento) => documento.id}
            legenda={`Documentos de ${dados.razao_social}`}
            aoAbrirLinha={(documento) => definir({ doc: documento.id })}
            virtualizar
            estados={{
              carregando: documentos.carregando,
              erro: documentos.erro,
              aoTentarNovamente: documentos.atualizar,
              vazioTitulo: pronto ? "Nenhum documento neste período" : "Escolha o período",
              vazioInstrucao: pronto
                ? "Se o certificado estiver válido, dispare a captura deste período — o documento pode ainda não ter sido distribuído pela SEFAZ."
                : "A API exige data inicial e final para listar o acervo.",
              vazioAcao:
                pronto && !somenteLeitura ? (
                  <BotaoLink variante="secundaria" href={`/dashboard/importacoes?empresa_ids=${dados.id}`}>
                    Disparar captura
                  </BotaoLink>
                ) : undefined,
              vazioIcone: "documento",
            }}
            rodape={
              <p className="nums text-xs text-tinta-suave">
                {numero(documentosNoPeriodo.length)} {plural(documentosNoPeriodo.length, "documento", "documentos")} ·{" "}
                {numero(documentosNoPeriodo.filter((documento) => documento.leiaute === "resumo").length)} só com resumo · clique numa linha para abrir o detalhe
              </p>
            }
          />
        </Cartao>
      ) : null}

      {aba === "execucoes" ? (
        <Cartao titulo="Execuções desta empresa" descricao="Histórico de capturas, com o motivo de cada falha">
          <Tabela
            linhas={execucoes.dados ?? []}
            colunas={colunasExecucoes(agora)}
            chaveDaLinha={(execucao) => execucao.id}
            legenda={`Execuções de ${dados.razao_social}`}
            virtualizar
            estados={{
              carregando: execucoes.carregando,
              erro: execucoes.erro,
              aoTentarNovamente: execucoes.atualizar,
              vazioTitulo: "Nenhuma execução registrada",
              vazioInstrucao: "Dispare a captura para criar o primeiro histórico desta empresa.",
              vazioIcone: "execucao",
            }}
            rodape={
              <p className="nums text-xs text-tinta-suave">
                {numero((execucoes.dados ?? []).length)} {plural((execucoes.dados ?? []).length, "execução", "execuções")} ·{" "}
                {numero((execucoes.dados ?? []).filter((execucao) => execucao.status === "erro").length)} com erro
              </p>
            }
          />
        </Cartao>
      ) : null}

      {aba === "integracoes" ? <AbaIntegracoes empresaId={dados.id} somenteLeitura={somenteLeitura} /> : null}

      <PainelDocumento
        documentoId={documentoAberto}
        aoFechar={() => definir({ doc: null })}
        aoExcluir={somenteLeitura ? undefined : (detalhe) => setExcluirDocumento(detalhe)}
        somenteLeitura={somenteLeitura}
      />

      <ModalEditarEmpresa aberto={editarAberto} aoFechar={() => setEditarAberto(false)} empresa={dados} aoSalvar={recarregar} />
      <ModalCertificado aberto={certificadoAberto} aoFechar={() => setCertificadoAberto(false)} empresaId={dados.id} aoSalvar={recarregar} />

      <DialogoConfirmacao
        aberto={excluirAberto}
        aoFechar={() => {
          setExcluirAberto(false);
          setErroExclusao(null);
        }}
        aoConfirmar={async () => {
          setExcluindo(true);
          setErroExclusao(null);
          try {
            await api.excluirEmpresa(dados.id);
            avisar({ tom: "ok", titulo: "Empresa excluída", descricao: dados.razao_social });
            router.replace("/dashboard/empresas");
          } catch (falha) {
            setErroExclusao(mensagemDoErro(falha, "excluir a empresa"));
          } finally {
            setExcluindo(false);
          }
        }}
        carregando={excluindo}
        erro={erroExclusao}
        tom="perigo"
        titulo={`Excluir ${dados.razao_social}`}
        consequencia="A empresa sai do cadastro junto com certificado, sincronismo e histórico de execuções. Os XMLs dela são apagados do disco."
        impacto={
          <span>
            {numero(documentosNoPeriodo.length)} documentos no período {rotuloPeriodo(periodo)} · {numero((sincronizacao.dados ?? []).length)} combinações de
            sincronismo. A captura automática desta empresa para imediatamente.
          </span>
        }
        exigirTexto="EXCLUIR"
        rotuloConfirmar="Excluir empresa"
      />

      <DialogoConfirmacao
        aberto={excluirDocumento !== null}
        aoFechar={() => {
          setExcluirDocumento(null);
          setErroExclusaoDocumento(null);
        }}
        aoConfirmar={async () => {
          if (!excluirDocumento) return;
          setExcluindoDocumento(true);
          setErroExclusaoDocumento(null);
          try {
            const resultado = await api.excluirDocumento(excluirDocumento.id);
            avisar({ tom: "ok", titulo: "Documento excluído", descricao: `${numero(resultado.arquivos_removidos)} arquivo removido do disco` });
            setExcluirDocumento(null);
            definir({ doc: null });
            documentos.atualizar();
          } catch (falha) {
            setErroExclusaoDocumento(mensagemDoErro(falha, "excluir o documento"));
          } finally {
            setExcluindoDocumento(false);
          }
        }}
        carregando={excluindoDocumento}
        erro={erroExclusaoDocumento}
        tom="perigo"
        titulo="Excluir este documento"
        consequencia={
          excluirDocumento
            ? `${ROTULO_TIPO[excluirDocumento.tipo] ?? excluirDocumento.tipo} ${excluirDocumento.numero ?? ""} sai do banco e o XML é apagado do disco.`
            : ""
        }
        impacto="Para recuperar, será preciso capturar o documento de novo pela SEFAZ, dentro do período de distribuição."
        rotuloConfirmar="Excluir"
      />
    </div>
  );
}

const colunasDocumentos: Array<ColunaTabela<DocumentoFiscal>> = [
  { id: "emissao", cabecalho: "Emissão", ordenavel: true, celula: (documento) => <span className="nums whitespace-nowrap">{dataCurta(documento.data_emissao)}</span> },
  { id: "tipo", cabecalho: "Tipo", celula: (documento) => <Etiqueta tom="neutro">{ROTULO_TIPO[documento.tipo]}</Etiqueta> },
  {
    id: "numero",
    cabecalho: "Número",
    celula: (documento) => (
      <span className="nums whitespace-nowrap">
        {documento.numero ?? "—"}
        {documento.serie ? <span className="ml-1.5 text-xs text-tinta-suave">série {documento.serie}</span> : null}
      </span>
    ),
  },
  {
    id: "parte",
    cabecalho: "Emitente / destinatário",
    largura: "min-w-56",
    celula: (documento) => {
      const nome = documento.direcao === "tomada" ? documento.emitente_nome : documento.destinatario_nome;
      return <span className="block truncate" title={nome ?? undefined}>{nome ?? "—"}</span>;
    },
  },
  { id: "valor", cabecalho: "Valor", alinhamento: "direita", numerica: true, celula: (documento) => <ValorMoeda valor={documento.valor_total} cancelado={documento.status === "cancelada"} /> },
  {
    id: "status",
    cabecalho: "Situação",
    celula: (documento) => (
      <span className="flex flex-wrap items-center gap-1.5">
        {documento.status === "cancelada" ? <Etiqueta tom="erro">Cancelada</Etiqueta> : <Etiqueta tom="ok">Normal</Etiqueta>}
        {documento.leiaute === "resumo" ? <Etiqueta tom="espera">só resumo</Etiqueta> : null}
      </span>
    ),
  },
  {
    id: "chave",
    cabecalho: "Chave de acesso",
    largura: "min-w-52",
    celula: (documento) => (
      <CopiavelMono valor={documento.chave_acesso} exibicao={`${documento.chave_acesso.slice(0, 8)}…${documento.chave_acesso.slice(-4)}`} rotulo={`Chave do documento ${documento.numero ?? documento.id}`} />
    ),
  },
];

function colunasExecucoes(agora: number): Array<ColunaTabela<ExecucaoImportacao>> {
  return [
    { id: "inicio", cabecalho: "Início", ordenavel: true, celula: (execucao) => <DataHora iso={execucao.iniciado_em} /> },
    { id: "tipo", cabecalho: "Tipo", celula: (execucao) => <Etiqueta tom="neutro">{ROTULO_TIPO[execucao.tipo as TipoDocumentoFiscal] ?? execucao.tipo}</Etiqueta> },
    { id: "status", cabecalho: "Situação", celula: (execucao) => <IndicadorEstado {...estadoDaExecucao(execucao.status)} titulo={execucao.mensagem_erro ?? undefined} /> },
    {
      id: "periodo",
      cabecalho: "Período",
      celula: (execucao) =>
        execucao.data_inicio && execucao.data_fim ? (
          <span className="nums whitespace-nowrap text-tinta-suave">
            {dataCurta(execucao.data_inicio)} – {dataCurta(execucao.data_fim)}
          </span>
        ) : (
          "—"
        ),
    },
    { id: "documentos", cabecalho: "Importados", alinhamento: "direita", numerica: true, celula: (execucao) => numero(execucao.documentos_importados) },
    {
      id: "duracao",
      cabecalho: "Duração",
      alinhamento: "direita",
      numerica: true,
      celula: (execucao) => (execucao.finalizado_em ? tempoDecorrido(execucao.iniciado_em, execucao.finalizado_em, agora) : "em curso"),
    },
    {
      id: "erro",
      cabecalho: "Mensagem",
      largura: "min-w-64",
      celula: (execucao) => (
        <span className="block truncate text-xs text-tinta-suave" title={execucao.mensagem_erro ?? execucao.aviso ?? undefined}>
          {execucao.mensagem_erro ?? execucao.aviso ?? "—"}
        </span>
      ),
    },
  ];
}

function AbaIntegracoes({ empresaId, somenteLeitura }: { empresaId: number; somenteLeitura: boolean }) {
  const { avisar } = useToast();
  const status = useRecurso(() => api.statusJettax(), []);
  const configuracao = useRecurso(() => api.obterJettaxEmpresa(empresaId), [empresaId], { automatico: false });
  const execucoes = useRecurso(() => api.listarExecucoesJettaxEmpresa(empresaId, 10), [empresaId]);
  const [salvando, setSalvando] = useState<string | null>(null);

  useEffect(() => {
    if (status.dados?.configurado) configuracao.atualizar();
    // A configuração só faz sentido com a integração ativa no escritório.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.dados?.configurado]);

  if (status.carregando) return <EsqueletoBloco linhas={4} />;
  if (status.erro) return <EstadoErro erro={status.erro} aoTentarNovamente={status.atualizar} contexto="carregar o status da integração Jettax" />;
  if (!status.dados?.configurado) {
    return (
      <EstadoVazio
        titulo="Integração Jettax não configurada"
        instrucao="O registro por empresa só existe depois que o token do escritório é salvo em Configurações."
        acao={<BotaoLink variante="secundaria" href="/dashboard/configuracoes?aba=integracoes">Abrir Configurações</BotaoLink>}
        icone="webhook"
      />
    );
  }

  async function salvar(campo: keyof Pick<JettaxConfiguracaoEmpresa, "ativa" | "baixar_nfes" | "baixar_nfes_enviadas">, valor: boolean) {
    setSalvando(campo);
    try {
      await api.salvarJettaxEmpresa(empresaId, { [campo]: valor });
      configuracao.atualizar();
      avisar({ tom: "ok", titulo: "Preferência salva", descricao: `${campo.replaceAll("_", " ")}: ${valor ? "ligado" : "desligado"}` });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível salvar", descricao: mensagemDoErro(falha, "salvar a configuração Jettax") });
    } finally {
      setSalvando(null);
    }
  }

  async function registrar() {
    setSalvando("registrar");
    try {
      const resultado = await api.registrarJettaxEmpresa(empresaId, false);
      configuracao.definir(resultado);
      avisar({ tom: "ok", titulo: "Empresa registrada no Jettax", descricao: `Status: ${resultado.status}` });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível registrar", descricao: mensagemDoErro(falha, "registrar a empresa no Jettax") });
    } finally {
      setSalvando(null);
    }
  }

  const dados = configuracao.dados;

  return (
    <div className="space-y-4">
      <Cartao
        titulo="Jettax"
        descricao={`Base ${status.dados.base_url} · saúde ${status.dados.saude} · ${numero(status.dados.empresas_registradas)} registradas`}
        acoes={
          somenteLeitura ? undefined : (
            <Botao variante="secundaria" tamanho="sm" onClick={registrar} carregando={salvando === "registrar"} iconeEsquerda={<Icone nome="enviar" className="h-3.5 w-3.5" />}>
              Registrar / atualizar cliente
            </Botao>
          )
        }
      >
        {configuracao.carregando ? (
          <EsqueletoBloco linhas={3} />
        ) : configuracao.erro ? (
          <Aviso tom="espera" titulo="Empresa ainda não registrada">
            {mensagemDoErro(configuracao.erro, "ler a configuração Jettax da empresa")}
          </Aviso>
        ) : dados ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <IndicadorEstado tom={dados.ativa ? "ok" : "neutro"} rotulo={dados.ativa ? "Ativa no Jettax" : "Inativa no Jettax"} icone={dados.ativa ? "verificar-circulo" : "pausa"} />
              <Etiqueta tom="neutro">status {dados.status}</Etiqueta>
              {dados.ultimo_erro ? <Etiqueta tom="erro" titulo={dados.ultimo_erro}>última falha</Etiqueta> : null}
              {dados.travado_em ? <Etiqueta tom="espera" titulo={`Travado em ${dataHora(dados.travado_em)}`}>travada</Etiqueta> : null}
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <Alternador rotulo="Baixar NFS-e" ligado={dados.baixar_nfes} aoMudar={(valor) => salvar("baixar_nfes", valor)} pendente={salvando === "baixar_nfes"} desabilitado={somenteLeitura} motivoDesabilitado={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined} />
              <Alternador rotulo="Baixar NF-e" ligado={dados.baixar_nfes_enviadas} aoMudar={(valor) => salvar("baixar_nfes_enviadas", valor)} pendente={salvando === "baixar_nfes_enviadas"} desabilitado={somenteLeitura} motivoDesabilitado={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined} />
              <Alternador rotulo="Integração ativa" ligado={dados.ativa} aoMudar={(valor) => salvar("ativa", valor)} pendente={salvando === "ativa"} desabilitado={somenteLeitura} motivoDesabilitado={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined} />
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-traco pt-3 text-sm sm:grid-cols-4">
              <Dado rotulo="Última sincronização" valor={dados.ultima_sincronizacao_em ? dataHora(dados.ultima_sincronizacao_em) : "—"} />
              <Dado rotulo="Último registro" valor={dados.ultimo_registro_em ? dataHora(dados.ultimo_registro_em) : "—"} />
              <Dado rotulo="Cursor NFS-e" valor={dados.ultimo_id_nfse ?? "—"} mono />
              <Dado rotulo="Falhas seguidas" valor={numero(dados.falhas_seguidas ?? 0)} tom={(dados.falhas_seguidas ?? 0) > 0 ? "erro" : undefined} />
            </dl>
          </div>
        ) : null}
      </Cartao>

      <Cartao titulo="Execuções Jettax" descricao="Últimas importações feitas por esta integração">
        {execucoes.carregando ? (
          <EsqueletoBloco linhas={3} />
        ) : execucoes.erro ? (
          <EstadoErro erro={execucoes.erro} aoTentarNovamente={execucoes.atualizar} contexto="carregar as execuções Jettax" />
        ) : (execucoes.dados ?? []).length === 0 ? (
          <EstadoVazio inline titulo="Nenhuma execução Jettax" instrucao="Registre a empresa e dispare uma importação para criar histórico." icone="webhook" />
        ) : (
          <ul className="divide-y divide-traco">
            {(execucoes.dados ?? []).map((execucao: JettaxExecucao) => (
              <li key={execucao.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm text-tinta">
                    {execucao.fluxo.toUpperCase()} · {numero(execucao.documentos_importados)} importados
                    {execucao.documentos_duplicados > 0 ? ` · ${numero(execucao.documentos_duplicados)} duplicados` : ""}
                  </p>
                  <p className="nums truncate text-xs text-tinta-suave" title={execucao.mensagem_erro ?? execucao.aviso ?? undefined}>
                    {execucao.iniciado_em ? dataHora(execucao.iniciado_em) : "—"} · origem {execucao.origem}
                    {execucao.mensagem_erro ? ` · ${execucao.mensagem_erro}` : ""}
                  </p>
                </div>
                <IndicadorEstado {...estadoDaExecucao(execucao.status)} />
              </li>
            ))}
          </ul>
        )}
      </Cartao>
    </div>
  );
}

function ModalEditarEmpresa({
  aberto,
  aoFechar,
  empresa,
  aoSalvar,
}: {
  aberto: boolean;
  aoFechar: () => void;
  empresa: {
    id: number;
    razao_social: string;
    cnpj_cpf: string;
    uf: string;
    ativa: boolean;
    sincronizar_automaticamente?: boolean;
    quais_tipos_sincronizar?: string | null;
    codigo_ibge?: string | null;
    inscricao_municipal?: string | null;
  };
  aoSalvar: () => void;
}) {
  const { avisar } = useToast();
  const [razao, setRazao] = useState(empresa.razao_social);
  const [uf, setUf] = useState(empresa.uf ?? "");
  const [ativa, setAtiva] = useState(empresa.ativa);
  const [automatica, setAutomatica] = useState(Boolean(empresa.sincronizar_automaticamente));
  const [tipos, setTipos] = useState<Set<TipoDocumentoFiscal>>(
    () =>
      new Set(
        (empresa.quais_tipos_sincronizar ?? "")
          .split(",")
          .map((tipo) => tipo.trim())
          .filter((tipo): tipo is TipoDocumentoFiscal => TIPOS.includes(tipo as TipoDocumentoFiscal))
      )
  );
  const [ibge, setIbge] = useState(empresa.codigo_ibge ?? "");
  const [municipal, setMunicipal] = useState(empresa.inscricao_municipal ?? "");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Reabrir o modal com a empresa mudada em outra aba não pode mostrar valor velho.
  useEffect(() => {
    if (!aberto) return;
    setRazao(empresa.razao_social);
    setUf(empresa.uf ?? "");
    setAtiva(empresa.ativa);
    setAutomatica(Boolean(empresa.sincronizar_automaticamente));
    setIbge(empresa.codigo_ibge ?? "");
    setMunicipal(empresa.inscricao_municipal ?? "");
    setErro(null);
  }, [aberto, empresa]);

  async function salvar() {
    if (!razao.trim()) {
      setErro("A razão social não pode ficar vazia.");
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      await api.atualizarEmpresa(empresa.id, {
        razao_social: razao.trim(),
        uf,
        ativa,
        sincronizar_automaticamente: automatica,
        quais_tipos_sincronizar: Array.from(tipos),
        codigo_ibge: ibge.trim(),
        inscricao_municipal: municipal.trim(),
      });
      avisar({ tom: "ok", titulo: "Empresa atualizada", descricao: razao.trim() });
      aoSalvar();
      aoFechar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "salvar a empresa"));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={aoFechar}
      titulo="Editar empresa"
      descricao={`${formatarCnpjCpf(empresa.cnpj_cpf)} · as mudanças valem para a captura automática e para os relatórios.`}
      largura="media"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={aoFechar}>
            Cancelar
          </Botao>
          <Botao variante="primaria" onClick={salvar} carregando={enviando}>
            Salvar alterações
          </Botao>
        </div>
      }
    >
      <div className="space-y-4">
        <Entrada rotulo="Razão social" obrigatorio value={razao} onChange={(evento) => setRazao(evento.target.value)} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Selecao rotulo="UF" value={uf} onChange={(evento) => setUf(evento.target.value)} opcoes={[{ valor: "", rotulo: "Não informar" }, ...UFS.map((item) => ({ valor: item.sigla, rotulo: `${item.sigla} · ${item.nome}` }))]} />
          <Entrada rotulo="Código IBGE do município" value={ibge} onChange={(evento) => setIbge(evento.target.value)} mono inputMode="numeric" descricao="Usado na NFS-e de alguns municípios." />
        </div>
        <Entrada rotulo="Inscrição municipal" value={municipal} onChange={(evento) => setMunicipal(evento.target.value)} mono descricao="Opcional: aparece no XML quando o emitente exige." />

        <div className="space-y-3 border-t border-traco pt-3">
          <Alternador
            rotulo="Empresa ativa"
            descricao="Inativa não entra na captura automática."
            ligado={ativa}
            aoMudar={setAtiva}
          />
          <Alternador
            rotulo="Sincronismo automático"
            descricao="Desligado, a captura só acontece quando alguém dispara manualmente."
            ligado={automatica}
            aoMudar={setAutomatica}
          />
          <div>
            <p className="mb-1.5 text-xs font-medium text-tinta">Tipos sincronizados</p>
            <p className="mb-2 text-xs text-tinta-suave">Sem nenhum marcado, o robô tenta os três tipos.</p>
            <div className="flex flex-wrap gap-4">
              {TIPOS.map((tipo) => (
                <Caixa
                  key={tipo}
                  rotulo={ROTULO_TIPO[tipo]}
                  compacta
                  checked={tipos.has(tipo)}
                  onChange={() =>
                    setTipos((atual) => {
                      const proximo = new Set(atual);
                      if (proximo.has(tipo)) proximo.delete(tipo);
                      else proximo.add(tipo);
                      return proximo;
                    })
                  }
                />
              ))}
            </div>
          </div>
        </div>

        {erro ? (
          <p role="alert" className="rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
            {erro}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

function ModalCertificado({ aberto, aoFechar, empresaId, aoSalvar }: { aberto: boolean; aoFechar: () => void; empresaId: number; aoSalvar: () => void }) {
  const { avisar } = useToast();
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [senha, setSenha] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  function fechar() {
    setArquivos([]);
    setSenha("");
    setErro(null);
    aoFechar();
  }

  async function enviar() {
    const arquivo = arquivos[0];
    if (!arquivo) {
      setErro("Escolha o arquivo .p12 ou .pfx do certificado.");
      return;
    }
    if (!senha) {
      setErro("Informe a senha do certificado — sem ela não há como abrir o arquivo.");
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const criado = await api.enviarCertificado(empresaId, senha, arquivo);
      avisar({ tom: "ok", titulo: "Certificado instalado", descricao: `Válido até ${dataCurta(criado.validade)}` });
      aoSalvar();
      fechar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "instalar o certificado"));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={fechar}
      titulo="Certificado A1"
      descricao="O arquivo é cifrado no servidor e a senha não volta ao navegador nem aparece em tela."
      largura="media"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={fechar}>
            Cancelar
          </Botao>
          <Botao variante="primaria" onClick={enviar} carregando={enviando} disabled={arquivos.length === 0}>
            Instalar certificado
          </Botao>
        </div>
      }
    >
      <div className="space-y-4">
        <CampoArquivo
          rotulo="Arquivo do certificado"
          obrigatorio
          aceita=".p12,.pfx"
          arquivos={arquivos}
          aoMudar={(lista) => setArquivos(lista.slice(0, 1))}
          descricao="Substitui o certificado atual desta empresa."
        />
        <Entrada
          rotulo="Senha do certificado"
          obrigatorio
          type="password"
          autoComplete="off"
          value={senha}
          onChange={(evento) => setSenha(evento.target.value)}
          descricao="Usada uma vez, para abrir o arquivo no servidor."
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

