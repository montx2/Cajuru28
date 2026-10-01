"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { numero, plural } from "@/lib/format";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { Area, Caixa, Selecao } from "@/components/ui/Campo";
import { Icone } from "@/components/ui/Icone";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import type { PendenciaImportacao, ResultadoSincronizacaoProcuracoes } from "@/lib/types";

interface Props {
  aberta: boolean;
  aoFechar: () => void;
  aoImportar: () => void;
}

const FONTES = [
  { valor: "planilha", rotulo: "Planilha do escritório" },
  { valor: "jettax360", rotulo: "Jettax 360" },
];

/**
 * De qual aba do painel a colagem veio. O painel tem duas abas — "Com
 * procuração" e "Sem procuração" — e a de procurações ainda filtra por
 * situação (Expirado, Na validade…). A aba declarada aqui só decide as
 * linhas em que a situação não aparece no próprio texto: quem cola a aba
 * "Sem procuração" está afirmando, pelo nome da aba, que o cliente não
 * autorizou — e isso vira `sem_autorizacao`, não "situação indeterminada".
 */
const SITUACOES_DA_ABA = [
  { valor: "", rotulo: "Aba “Com procuração” — detectar pelo texto (recomendado)" },
  { valor: "expirada", rotulo: "Aba “Com procuração” com filtro Expirado" },
  { valor: "ativa", rotulo: "Aba “Com procuração” com filtro Na validade" },
  { valor: "sem_procuracao", rotulo: "Aba “Sem procuração”" },
];

/** Pendência que o operador resolve cadastrando a empresa. */
const PENDENCIA_SEM_EMPRESA = "EMPRESA_NAO_CADASTRADA";

/**
 * Importação da lista de procurações por texto colado ou arquivo.
 *
 * Por que isto existe: o painel do Jettax 360 mostra a relação de clientes com
 * procuração no e-CAC, mas o fornecedor não publica API para essa tela. Em vez
 * de depender de um endpoint que não existe, o operador traz a lista — e o
 * sistema faz com ela exatamente o que faria com uma resposta de API: casa
 * pelo CNPJ/CPF normalizado, respeita a precedência entre fontes e registra
 * cada linha aproveitada ou recusada.
 *
 * Colar duas vezes é seguro: a chave é o documento, não a ordem da tela.
 */
export function ImportarLista({ aberta, aoFechar, aoImportar }: Props) {
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();

  const [texto, setTexto] = useState("");
  const [fonte, setFonte] = useState("planilha");
  const [situacaoPadrao, setSituacaoPadrao] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoSincronizacaoProcuracoes | null>(null);
  const [pendenciasSelecionadas, setPendenciasSelecionadas] = useState<string[]>([]);
  const arquivoRef = useRef<HTMLInputElement>(null);

  // Novo resultado: as pendências nascem todas marcadas. O caminho de um
  // clique é o padrão; desmarcar é a exceção — a lista do painel inclui
  // outorgantes que não são clientes do escritório, e é o operador quem sabe
  // quais são.
  useEffect(() => {
    if (!resultado) {
      setPendenciasSelecionadas([]);
      return;
    }
    setPendenciasSelecionadas(
      resultado.erros
        .filter((item) => item.codigo === PENDENCIA_SEM_EMPRESA)
        .map((item) => item.documento)
    );
  }, [resultado]);

  const linhasColadas = useMemo(
    () => texto.split("\n").filter((linha) => linha.trim()).length,
    [texto]
  );

  function limpar() {
    setTexto("");
    setResultado(null);
    if (arquivoRef.current) arquivoRef.current.value = "";
  }

  function concluir(dados: ResultadoSincronizacaoProcuracoes) {
    setResultado(dados);
    const aproveitados = dados.criados + dados.atualizados + dados.inalterados;
    avisar({
      tom: aproveitados > 0 ? "ok" : "info",
      titulo: `Importação de ${dados.fonte}`,
      descricao: dados.mensagem,
    });
    aoImportar();
  }

  async function importarTexto() {
    if (!texto.trim()) return;
    setEnviando(true);
    try {
      concluir(
        await api.importarListaProcuracoes({
          texto,
          fonte,
          situacao_padrao: situacaoPadrao,
        })
      );
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Importação recusada", descricao: mensagemDoErro(erro, "importar a lista") });
    } finally {
      setEnviando(false);
    }
  }

  async function importarArquivo(arquivo: File) {
    setEnviando(true);
    try {
      concluir(await api.importarPlanilhaProcuracoes(arquivo, { fonte, situacaoPadrao }));
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Arquivo recusado", descricao: mensagemDoErro(erro, "importar o arquivo") });
    } finally {
      setEnviando(false);
      if (arquivoRef.current) arquivoRef.current.value = "";
    }
  }

  /**
   * O fechamento do ciclo em um clique: cadastra as pendências marcadas (nome
   * e documento vieram com a lista; a UF o servidor descobre pelo CNPJ) e
   * importa a mesma colagem de novo — a colagem ainda está na caixa, e as
   * linhas que viraram pendência agora encontram dono. Quem a consulta
   * pública não resolve continua pendência, dizendo o que falta.
   */
  async function cadastrarPendencias() {
    const marcadas = (resultado?.erros ?? []).filter(
      (item) => item.codigo === PENDENCIA_SEM_EMPRESA && pendenciasSelecionadas.includes(item.documento)
    );
    if (marcadas.length === 0) return;
    setEnviando(true);
    try {
      const lote = await api.cadastrarEmpresasPendencias(
        marcadas.map((item) => ({ documento: item.documento, razao_social: item.nome || "" }))
      );
      avisar({
        tom: lote.erros > 0 ? "espera" : "ok",
        titulo: `${numero(lote.criadas)} ${plural(lote.criadas, "empresa cadastrada", "empresas cadastradas")}`,
        descricao:
          lote.erros > 0
            ? `${numero(lote.erros)} sem UF confirmada — cadastre em Empresas. A lista foi importada de novo.`
            : "A lista da caixa foi importada de novo para valer as novas empresas.",
      });
      await importarTexto();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Cadastro recusado", descricao: mensagemDoErro(erro, "cadastrar as empresas") });
    } finally {
      setEnviando(false);
    }
  }

  const pendencias: PendenciaImportacao[] = resultado?.erros ?? [];
  const semEmpresa = pendencias.filter((item) => item.codigo === PENDENCIA_SEM_EMPRESA);
  const outras = pendencias.filter((item) => item.codigo !== PENDENCIA_SEM_EMPRESA);

  return (
    <Modal
      aberto={aberta}
      aoFechar={() => {
        limpar();
        aoFechar();
      }}
      titulo="Importar lista de procurações"
      descricao="Cole a lista do escritório ou envie o arquivo exportado. Uma nova importação atualiza os registros sem duplicar."
      largura="larga"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {resultado ? (
            <Botao variante="sutil" onClick={limpar}>
              Importar outra página
            </Botao>
          ) : null}
          <Botao
            variante="sutil"
            onClick={() => {
              limpar();
              aoFechar();
            }}
          >
            Fechar
          </Botao>
          <Botao
            variante="primaria"
            carregando={enviando}
            disabled={somenteLeitura || !texto.trim()}
            title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
            onClick={importarTexto}
            iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}
          >
            Importar lista
          </Botao>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Selecao
            rotulo="Origem do dado"
            value={fonte}
            onChange={(evento) => setFonte(evento.target.value)}
            disabled={somenteLeitura}
            opcoes={FONTES}
            descricao="A origem define qual dado prevalece numa importação futura."
          />
          <Selecao
            rotulo="Situação da aba"
            value={situacaoPadrao}
            onChange={(evento) => setSituacaoPadrao(evento.target.value)}
            disabled={somenteLeitura}
            opcoes={SITUACOES_DA_ABA}
            descricao="Só é usada nas linhas em que a situação não aparece no texto."
          />
        </div>

        {fonte === "jettax360" ? (
          <details className="rounded-controle border border-traco bg-fundo-afundado px-3 py-2 text-sm text-tinta-suave">
            <summary className="cursor-pointer font-medium text-tinta">Como preparar a lista exportada</summary>
            <p className="mt-2 leading-6">
              Na lista exportada do Jettax 360, copie a tabela com início, vencimento e situação. Se houver páginas ou abas separadas,
              importe uma de cada vez e informe a situação da aba. O CNPJ/CPF evita duplicatas.
            </p>
          </details>
        ) : null}

        <Area
          rotulo="Lista copiada da tela"
          rows={10}
          mono
          value={texto}
          onChange={(evento) => setTexto(evento.target.value)}
          disabled={somenteLeitura}
          placeholder={"CLIENTE UM LTDA\n12.345.678/0001-95\nSim\n01/02/2024\n31/12/2030\nVálida"}
          descricao="Nome numa linha e CNPJ/CPF na seguinte, ou tudo na mesma linha — os dois formatos funcionam."
          nota={linhasColadas > 0 ? `${numero(linhasColadas)} ${plural(linhasColadas, "linha", "linhas")} coladas` : undefined}
        />

        <div className="flex flex-wrap items-center gap-2 rounded-controle border border-borda-controle p-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-tinta">Arquivo exportado</p>
            <p className="text-xs text-tinta-suave">
              Envie o CSV/TXT exportado do painel. O leitor identifica sozinho se o arquivo tem cabeçalho.
            </p>
          </div>
          <input
            ref={arquivoRef}
            type="file"
            accept=".csv,.txt,.tsv,text/csv,text/plain"
            className="hidden"
            onChange={(evento) => {
              const arquivo = evento.target.files?.[0];
              if (arquivo) importarArquivo(arquivo);
            }}
          />
          <Botao
            variante="secundaria"
            tamanho="sm"
            disabled={somenteLeitura || enviando}
            title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
            onClick={() => arquivoRef.current?.click()}
            iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}
          >
            Enviar arquivo
          </Botao>
        </div>

        {resultado ? (
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { rotulo: "Criadas", valor: resultado.criados },
                { rotulo: "Atualizadas", valor: resultado.atualizados },
                { rotulo: "Sem mudança", valor: resultado.inalterados },
                { rotulo: "Pendentes", valor: resultado.ignorados + resultado.invalidos },
              ].map((item) => (
                <div key={item.rotulo} className="rounded-controle border border-borda-controle p-2.5">
                  <dt className="text-2xs uppercase tracking-[.04em] text-tinta-fraca">{item.rotulo}</dt>
                  <dd className="nums text-lg text-tinta">{numero(item.valor)}</dd>
                </div>
              ))}
            </dl>

            {semEmpresa.length > 0 ? (
              <Aviso
                tom="espera"
                icone="empresa"
                titulo={`${numero(semEmpresa.length)} ${plural(semEmpresa.length, "documento fora da carteira", "documentos fora da carteira")}`}
              >
                Nada foi criado por conta própria: a empresa precisa de UF e de cadastro completo para entrar nas
                rotinas fiscais. Marque quem é cliente do escritório e cadastre num clique — a UF é descoberta pelo
                CNPJ e a lista é importada de novo em seguida.
                <ul className="mt-2 max-h-56 space-y-0.5 overflow-y-auto">
                  {semEmpresa.map((item) => (
                    <li key={item.documento}>
                      <Caixa
                        compacta
                        rotulo={
                          <span className="font-mono text-2xs">
                            {item.documento}
                            {item.nome ? <span className="font-sans text-tinta-suave"> · {item.nome}</span> : null}
                          </span>
                        }
                        checked={pendenciasSelecionadas.includes(item.documento)}
                        disabled={somenteLeitura || enviando}
                        onChange={() =>
                          setPendenciasSelecionadas((atual) =>
                            atual.includes(item.documento)
                              ? atual.filter((documento) => documento !== item.documento)
                              : [...atual, item.documento]
                          )
                        }
                      />
                    </li>
                  ))}
                </ul>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Botao
                    variante="primaria"
                    tamanho="sm"
                    carregando={enviando}
                    disabled={somenteLeitura || pendenciasSelecionadas.length === 0}
                    title={
                      somenteLeitura
                        ? MOTIVO_SOMENTE_LEITURA
                        : pendenciasSelecionadas.length === 0
                          ? "Marque ao menos uma empresa"
                          : undefined
                    }
                    onClick={cadastrarPendencias}
                    iconeEsquerda={<Icone nome="adicionar" className="h-4 w-4" />}
                  >
                    Cadastrar {plural(pendenciasSelecionadas.length, "empresa", "empresas")} e importar de novo
                  </Botao>
                  <Botao
                    variante="sutil"
                    tamanho="sm"
                    disabled={somenteLeitura || enviando}
                    onClick={() =>
                      setPendenciasSelecionadas((atual) =>
                        atual.length === semEmpresa.length ? [] : semEmpresa.map((item) => item.documento)
                      )
                    }
                  >
                    {pendenciasSelecionadas.length === semEmpresa.length ? "Desmarcar todas" : "Marcar todas"}
                  </Botao>
                </div>
              </Aviso>
            ) : null}

            {outras.length > 0 ? (
              <Aviso tom="erro" icone="alerta" titulo={`${numero(outras.length)} ${plural(outras.length, "linha não aproveitada", "linhas não aproveitadas")}`}>
                <ul className="space-y-1">
                  {outras.slice(0, 8).map((item, indice) => (
                    <li key={`${item.documento}-${indice}`} className="text-2xs">
                      <span className="font-mono">{item.documento || "—"}</span>
                      {item.nome ? <span className="text-tinta-suave"> · {item.nome}</span> : null} — {item.mensagem}
                    </li>
                  ))}
                </ul>
              </Aviso>
            ) : null}
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
