"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { bytesParaTexto, chaveEmGrupos, dataCurta, dataHora, mesAno, numero, nsuFormatado, tempoRelativo } from "@/lib/format";
import { estadoDoDocumento } from "@/lib/estados";
import { useRecurso } from "@/lib/useRecurso";
import { ROTULO_TIPO, type DocumentoDetalhe, type TipoDocumentoFiscal } from "@/lib/types";
import { Botao } from "@/components/ui/Botao";
import { Dado } from "@/components/ui/Dado";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { ChaveAcesso, Cnpj, ValorMoeda } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Painel } from "@/components/ui/Painel";
import { useToast } from "@/components/ui/Toast";

export interface PainelDocumentoProps {
  documentoId: number | null;
  aoFechar: () => void;
  /** A exclusão é confirmada pela tela dona da lista: ela conhece o impacto. */
  aoExcluir?: (detalhe: DocumentoDetalhe) => void;
  somenteLeitura?: boolean;
}

/**
 * Detalhe do documento em painel lateral: o operador confere a chave contra o
 * XML do cliente sem perder a lista de origem — `Esc` devolve o foco à linha.
 */
export function PainelDocumento({ documentoId, aoFechar, aoExcluir, somenteLeitura }: PainelDocumentoProps) {
  return (
    <Painel
      aberto={documentoId !== null}
      aoFechar={aoFechar}
      titulo={documentoId !== null ? `Documento #${numero(documentoId)}` : "Documento"}
      contexto="Acervo de documentos fiscais"
      acoes={
        <Link
          href="/dashboard/documentos"
          className="flex h-9 items-center gap-1.5 rounded-controle px-2 text-xs font-medium text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
        >
          <Icone nome="documento" className="h-4 w-4" />
          Acervo
        </Link>
      }
    >
      {documentoId !== null ? (
        <ConteudoDocumento id={documentoId} aoExcluir={aoExcluir} somenteLeitura={somenteLeitura} />
      ) : null}
    </Painel>
  );
}

function ConteudoDocumento({ id, aoExcluir, somenteLeitura }: { id: number; aoExcluir?: (detalhe: DocumentoDetalhe) => void; somenteLeitura?: boolean }) {
  const recurso = useRecurso(() => api.detalheDocumento(id), [id]);
  const { avisar } = useToast();
  const [xml, setXml] = useState<string | null>(null);
  const [carregandoXml, setCarregandoXml] = useState(false);
  const [erroXml, setErroXml] = useState<string | null>(null);
  const [baixando, setBaixando] = useState(false);

  if (recurso.carregando) {
    return (
      <div className="space-y-6" aria-busy="true">
        <EsqueletoBloco linhas={2} />
        <EsqueletoBloco linhas={6} />
        <EsqueletoBloco linhas={4} />
      </div>
    );
  }

  if (recurso.erro || !recurso.dados) {
    return <EstadoErro erro={recurso.erro ?? new Error("Documento não encontrado")} aoTentarNovamente={recurso.atualizar} contexto="carregar o detalhe do documento" />;
  }

  const documento = recurso.dados;
  const estado = estadoDoDocumento(documento);
  const tipo = ROTULO_TIPO[(documento.tipo as TipoDocumentoFiscal) ?? "nfe"] ?? documento.tipo;

  async function verXml() {
    setCarregandoXml(true);
    setErroXml(null);
    try {
      setXml(await api.obterXmlTexto(id));
    } catch (falha) {
      setErroXml(falha instanceof Error ? falha.message : "Não foi possível ler o XML.");
    } finally {
      setCarregandoXml(false);
    }
  }

  async function baixarXml() {
    setBaixando(true);
    try {
      // Cookie HttpOnly não viaja em `<a download>` cross-origin: o arquivo vem
      // por `fetch` + blob e o nome real sai do `content-disposition`.
      await api.baixarXmlDocumento(id, `${documento.chave_acesso || `documento-${id}`}.xml`);
      avisar({ tom: "ok", titulo: "XML baixado", descricao: documento.chave_acesso ? chaveEmGrupos(documento.chave_acesso) : undefined });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível baixar o XML", descricao: falha instanceof Error ? falha.message : undefined });
    } finally {
      setBaixando(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <div className="flex flex-wrap items-center gap-2">
          <IndicadorEstado {...estado} titulo={documento.status === "cancelada" ? (documento.motivo_cancelamento ?? "Cancelada") : undefined} />
          <span className="rounded-badge border border-traco bg-neutro-tenue px-1.5 py-0.5 text-xs font-medium text-neutro">{tipo}</span>
          <span className="text-xs text-tinta-suave">{documento.direcao === "tomada" ? "Tomada (recebida)" : "Prestada (emitida)"}</span>
        </div>
        <h3 className="mt-2 text-md font-semibold text-tinta-forte">
          {documento.numero ? `${tipo} nº ${documento.numero}` : "Documento sem número"}
          {documento.serie ? <span className="ml-2 text-sm font-normal text-tinta-suave">série {documento.serie}</span> : null}
        </h3>
        <p className="mt-1 text-sm text-tinta-suave">
          <ValorMoeda valor={documento.valor_total} cancelado={documento.status === "cancelada"} className="font-medium text-tinta-forte" />
          <span className="mx-2 text-traco-forte">·</span>
          emissão {dataCurta(documento.data_emissao)}
          <span className="mx-2 text-traco-forte">·</span>
          competência {documento.competencia ? mesAno(documento.competencia) : "—"}
        </p>
        {documento.status === "cancelada" && documento.motivo_cancelamento ? (
          <p className="mt-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
            <span className="font-medium">Motivo do cancelamento: </span>
            {documento.motivo_cancelamento}
            {documento.cancelado_em ? <span className="nums ml-1 text-xs">· {dataHora(documento.cancelado_em)}</span> : null}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="chave-do-documento">
        <h4 id="chave-do-documento" className="text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">
          Chave de acesso
        </h4>
        <div className="mt-1.5 rounded-controle border border-traco bg-fundo-afundado px-3 py-2">
          <ChaveAcesso valor={documento.chave_acesso} />
          <p className="mt-1 text-2xs text-tinta-suave">{numero(somenteDigitosChave(documento.chave_acesso))} dígitos · grupos de 4</p>
        </div>
      </section>

      <section aria-labelledby="dados-do-documento">
        <h4 id="dados-do-documento" className="text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">
          Dados
        </h4>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <Dado rotulo="Empresa" valor={documento.empresa_razao_social} href={`/dashboard/empresa?id=${documento.empresa_id}`} />
          <Dado rotulo="CNPJ da empresa" valor={<Cnpj valor={documento.empresa_cnpj} />} />
          <Dado rotulo="UF" valor={documento.empresa_uf || "—"} />
          <Dado rotulo="Leiaute" valor={documento.leiaute === "resumo" ? "Resumo (resNFe)" : documento.leiaute === "metadados" ? "Metadados (sem XML)" : "XML completo"} />
          <Dado rotulo="NSU" valor={nsuFormatado(documento.nsu ?? null)} mono />
          <Dado rotulo="Origem" valor={documento.origem || "—"} />
          <Dado rotulo="Importado" valor={documento.importado_em ? tempoRelativo(documento.importado_em) : "—"} dica={dataHora(documento.importado_em)} />
          <Dado rotulo="Execução" valor={documento.execucao_id ? `#${numero(documento.execucao_id)}` : "—"} />
          <Dado rotulo="XML no disco" valor={documento.xml_disponivel ? `sim · ${bytesParaTexto(documento.xml_bytes)}` : "não"} />
        </dl>
      </section>

      <section aria-labelledby="partes-do-documento" className="grid gap-4 sm:grid-cols-2">
        <div>
          <h4 id="partes-do-documento" className="text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">
            Emitente
          </h4>
          <p className="mt-1 text-sm text-tinta">{documento.emitente_nome || "—"}</p>
          <Cnpj valor={documento.emitente_documento} className="mt-0.5" />
        </div>
        <div>
          <h4 className="text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">Destinatário</h4>
          <p className="mt-1 text-sm text-tinta">{documento.destinatario_nome || "—"}</p>
          <Cnpj valor={documento.destinatario_documento} className="mt-0.5" />
        </div>
      </section>

      <section aria-labelledby="xml-do-documento">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 id="xml-do-documento" className="text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">
            XML
          </h4>
          <div className="flex flex-wrap items-center gap-2">
            {xml === null ? (
              <Botao tamanho="sm" variante="sutil" onClick={verXml} carregando={carregandoXml} iconeEsquerda={<Icone nome="codigo" className="h-3.5 w-3.5" />}>
                Ver XML formatado
              </Botao>
            ) : (
              <Botao tamanho="sm" variante="sutil" onClick={() => setXml(null)} iconeEsquerda={<Icone nome="fechar" className="h-3.5 w-3.5" />}>
                Ocultar XML
              </Botao>
            )}
          </div>
        </div>
        {erroXml ? (
          <p role="alert" className="mt-2 text-sm text-erro">
            {erroXml} Use “Baixar XML” para obter o arquivo diretamente.
          </p>
        ) : null}
        {xml !== null ? <VisualizadorXml texto={xml} /> : null}
      </section>

      <div className="flex flex-wrap items-center gap-2 border-t border-traco pt-4">
        <Botao variante="primaria" tamanho="sm" onClick={baixarXml} carregando={baixando} iconeEsquerda={<Icone nome="baixar" className="h-4 w-4" />}>
          Baixar XML
        </Botao>
        <Link
          href={`/dashboard/empresa?id=${documento.empresa_id}`}
          className="inline-flex h-8 items-center gap-1.5 rounded-controle px-2.5 text-sm font-medium text-acento underline-offset-4 hover:underline"
        >
          <Icone nome="empresa" className="h-4 w-4" />
          Ver empresa
        </Link>
        {aoExcluir && !somenteLeitura ? (
          <Botao
            variante="perigo-sutil"
            tamanho="sm"
            className="ml-auto"
            onClick={() => aoExcluir(documento)}
            iconeEsquerda={<Icone nome="excluir" className="h-4 w-4" />}
          >
            Excluir documento
          </Botao>
        ) : null}
      </div>
    </div>
  );
}

function somenteDigitosChave(chave: string): number {
  return chave.replace(/\D/g, "").length;
}


const LIMITE_EXIBICAO = 400_000;

/** Destaque leve de sintaxe: tag, atributo e valor. Sem biblioteca externa. */
function VisualizadorXml({ texto }: { texto: string }) {
  const truncado = texto.length > LIMITE_EXIBICAO;
  const visivel = truncado ? texto.slice(0, LIMITE_EXIBICAO) : texto;
  const partes = visivel.split(/(<[^>]*>)/g);

  return (
    <div className="mt-2">
      <pre className="rolagem-fina max-h-96 overflow-auto rounded-cartao border border-grafite-traco bg-grafite p-3 font-mono text-xs leading-5 text-sobre-grafite">
        <code>
          {partes.map((parte, indice) =>
            parte.startsWith("<") ? <TagXml key={`${indice}-${parte.slice(0, 12)}`} texto={parte} /> : <span key={indice}>{parte}</span>
          )}
        </code>
      </pre>
      {truncado ? (
        <p className="mt-1 text-xs text-tinta-suave">
          Exibição limitada a {numero(LIMITE_EXIBICAO)} caracteres. O arquivo completo está em “Baixar XML”.
        </p>
      ) : null}
    </div>
  );
}

function TagXml({ texto }: { texto: string }) {
  const correspondencia = /^<(\/?)([\w:.-]+)([\s\S]*?)(\/?)>$/.exec(texto);
  if (!correspondencia) return <span className="text-sobre-grafite/70">{texto}</span>;
  const [, fechamento, nome, atributos, autoFechamento] = correspondencia;
  return (
    <span className="text-sobre-grafite/70">
      {"<"}
      {fechamento}
      <span className="font-medium text-acento">{nome}</span>
      {atributos ? <AtributosXml texto={atributos ?? ""} /> : null}
      {autoFechamento}
      {">"}
    </span>
  );
}

function AtributosXml({ texto }: { texto: string }) {
  const partes = texto.split(/([\w:.-]+="[^"]*")/g).filter((parte) => parte !== "");
  return (
    <>
      {partes.map((parte, indice) => {
        const separador = parte.indexOf("=");
        if (!parte.includes("=") || separador < 1) return <span key={indice}>{parte}</span>;
        return (
          <span key={indice}>
            <span className="text-espera">{parte.slice(0, separador)}</span>
            <span>=</span>
            <span className="text-ok">{parte.slice(separador + 1)}</span>
          </span>
        );
      })}
    </>
  );
}
