"use client";

import { useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { numero, plural } from "@/lib/format";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { Area, Selecao } from "@/components/ui/Campo";
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
  { valor: "jettax360", rotulo: "Jettax 360 (painel Prevenção → e-CAC)" },
  { valor: "planilha", rotulo: "Planilha do escritório" },
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
  const [fonte, setFonte] = useState("jettax360");
  const [situacaoPadrao, setSituacaoPadrao] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoSincronizacaoProcuracoes | null>(null);
  const arquivoRef = useRef<HTMLInputElement>(null);

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
      descricao="Cole o que está na tela do fornecedor ou envie o arquivo exportado. Rodar de novo não duplica nada."
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
        <Aviso tom="info" icone="cadeado" titulo="Como copiar do painel do Jettax">
          Abra <span className="font-mono text-2xs">Prevenção → e-CAC → Procurações</span>, selecione a tabela inteira
          (inclusive as colunas <span className="font-medium">INÍCIO</span>, <span className="font-medium">VENCIMENTO</span> e{" "}
          <span className="font-medium">SITUAÇÃO</span>) e cole aqui. O painel divide a lista em abas —{" "}
          <span className="font-medium">Com procuração</span> e <span className="font-medium">Sem procuração</span> — e
          pagina os resultados: cole uma página de cada vez, informando acima de qual aba ela veio. A chave é o
          CNPJ/CPF, então colar a mesma página de novo não cria duplicata — e a barra de filtros que vier junto na
          colagem é descartada sem alterar as linhas.
        </Aviso>

        <div className="grid gap-3 sm:grid-cols-2">
          <Selecao
            rotulo="Origem do dado"
            value={fonte}
            onChange={(evento) => setFonte(evento.target.value)}
            disabled={somenteLeitura}
            opcoes={FONTES}
            descricao="Define a precedência: dado do Jettax não é sobrescrito por planilha."
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
            <p className="text-sm text-tinta">Tem botão de exportar?</p>
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
                rotinas fiscais, e a lista do Jettax inclui outorgantes que não são clientes do escritório. Cadastre em{" "}
                <span className="font-medium">Empresas</span> quem for cliente e importe de novo.
                <ul className="mt-2 space-y-1">
                  {semEmpresa.slice(0, 12).map((item) => (
                    <li key={item.documento} className="font-mono text-2xs">
                      {item.documento}
                      {item.nome ? <span className="font-sans text-tinta-suave"> · {item.nome}</span> : null}
                    </li>
                  ))}
                </ul>
                {semEmpresa.length > 12 ? (
                  <p className="mt-1 text-2xs text-tinta-suave">e mais {numero(semEmpresa.length - 12)}…</p>
                ) : null}
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
