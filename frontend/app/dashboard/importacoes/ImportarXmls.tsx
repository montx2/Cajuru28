"use client";

/**
 * Importação manual de XMLs prontos — ZIP ou arquivos soltos exportados de
 * outro sistema. Este fluxo é propositalmente separado do cadastro de
 * empresas/certificados: para importar notas não há senha de A1 nem UF.
 */

import { useState } from "react";
import { api } from "@/lib/api";
import { numero, plural } from "@/lib/format";
import { mensagemDoErro } from "@/lib/erros";
import { ROTULO_TIPO, type ImportacaoXmlResposta } from "@/lib/types";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { useToast } from "@/components/ui/Toast";
import { Aviso } from "@/components/ui/Aviso";
import { Cartao } from "@/components/ui/Cartao";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { Botao } from "@/components/ui/Botao";
import { Dado } from "@/components/ui/Dado";
import { Cnpj } from "@/components/ui/Formatadores";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Modal } from "@/components/ui/Modal";

const ROTULO_STATUS: Record<string, string> = {
  importado: "Importada",
  duplicada: "Já existia",
  sem_empresa: "Sem empresa",
  nao_reconhecido: "Não reconhecido",
  ignorado: "Ignorado",
  erro: "Falhou",
};

const TOM_DO_STATUS: Record<string, "ok" | "neutro" | "erro"> = {
  importado: "ok",
  duplicada: "neutro",
  sem_empresa: "neutro",
  nao_reconhecido: "neutro",
  ignorado: "neutro",
  erro: "erro",
};

interface ImportadorXmlProps {
  /** Atualiza o acervo que estiver atrás do modal após uma importação válida. */
  aoConcluir?: () => void;
}

/**
 * Conteúdo único usado tanto na tela de Importações quanto no atalho de
 * Documentos. Assim os dois caminhos enviam os mesmos arquivos à mesma API.
 */
function ImportadorXml({ aoConcluir }: ImportadorXmlProps) {
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<ImportacaoXmlResposta | null>(null);

  const podeEnviar = arquivos.length > 0 && !somenteLeitura;

  async function enviar() {
    if (!podeEnviar) return;
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await api.importarXmls(arquivos);
      setResultado(resposta);
      aoConcluir?.();
      avisar({
        tom: "ok",
        titulo: plural(resposta.importados, "nota importada", "notas importadas"),
        descricao: `${plural(resposta.duplicadas, "nota já existia", "notas já existiam")} · ${plural(
          resposta.sem_empresa,
          "CNPJ fora do cadastro",
          "CNPJs fora do cadastro"
        )}`,
      });
    } catch (excecao) {
      setErro(mensagemDoErro(excecao));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="space-y-4">
      {erro ? (
        <Aviso tom="erro" compacto urgente>
          {erro}
        </Aviso>
      ) : null}

      {resultado ? (
        <ResultadoImportacao resultado={resultado} />
      ) : (
        <CampoArquivo
          rotulo="XMLs ou arquivo ZIP"
          aceita=".zip,.xml"
          multiplo
          arquivos={arquivos}
          aoMudar={setArquivos}
          maxBytes={100 * 1024 * 1024}
          descricao="Selecione um .zip com as notas ou os .xml soltos. Até 200 XMLs por lote; cada XML de até 2 MB."
          textoArraste="Arraste as notas em XML ou um arquivo ZIP aqui"
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-traco pt-3">
        <p className="max-w-leitura text-xs leading-5 text-tinta-suave">
          {resultado
            ? "Importação concluída — revise os itens acima."
            : "A nota é associada pelo CNPJ do destinatário ou, em nota prestada, pelo CNPJ do emitente. Não é necessário enviar certificado, senha ou UF."}
        </p>
        {resultado ? null : (
          <Botao
            variante="primaria"
            onClick={enviar}
            carregando={enviando}
            disabled={!podeEnviar}
            title={
              somenteLeitura
                ? "Seu papel é somente leitura"
                : arquivos.length === 0
                  ? "Selecione um .zip ou arquivos .xml antes de importar"
                  : undefined
            }
          >
            Importar notas
          </Botao>
        )}
      </div>
    </div>
  );
}

function ResultadoImportacao({ resultado }: { resultado: ImportacaoXmlResposta }) {
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-5">
        <Dado destaque rotulo="Arquivos" valor={numero(resultado.total)} />
        <Dado destaque rotulo="Importadas" valor={numero(resultado.importados)} tom="ok" />
        <Dado destaque rotulo="Já existiam" valor={numero(resultado.duplicadas)} />
        <Dado destaque rotulo="Sem empresa" valor={numero(resultado.sem_empresa)} />
        <Dado
          destaque
          rotulo="Com erro"
          valor={numero(resultado.erros + resultado.nao_reconhecidos)}
          tom={resultado.erros + resultado.nao_reconhecidos > 0 ? "erro" : undefined}
        />
      </dl>

      <div className="caixa-tabela max-h-80">
        <table className="tabela-dados">
          <caption className="sr-only">Arquivos processados</caption>
          <thead>
            <tr>
              <th scope="col">Arquivo</th>
              <th scope="col">Empresa</th>
              <th scope="col">Situação</th>
              <th scope="col">Mensagem</th>
            </tr>
          </thead>
          <tbody>
            {resultado.itens.map((item, indice) => (
              <tr key={`${item.chave}-${indice}`}>
                <td className="text-xs text-tinta-suave">
                  {item.origem}
                  {item.tipo ? <span className="ml-1 text-tinta-fraca">· {ROTULO_TIPO[item.tipo as keyof typeof ROTULO_TIPO] ?? item.tipo}</span> : null}
                </td>
                <th scope="row">
                  <span className="block truncate text-tinta">{item.razao_social || "—"}</span>
                  {item.cnpj_cpf ? <Cnpj valor={item.cnpj_cpf} copiar={false} className="text-xs text-tinta-suave" /> : null}
                </th>
                <td>
                  <Etiqueta tom={TOM_DO_STATUS[item.status] ?? "neutro"}>{ROTULO_STATUS[item.status] ?? item.status}</Etiqueta>
                </td>
                <td className="max-w-0">
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

/** Caminho completo na tela de Importações. */
export function ImportarXmls({ aoConcluir }: ImportadorXmlProps) {
  return (
    <Cartao
      titulo="Importar notas por XML"
      descricao="Envie notas que você já recebeu de outro sistema. Este caminho não consulta a SEFAZ e não pede certificado, senha ou UF."
    >
      <ImportadorXml aoConcluir={aoConcluir} />
    </Cartao>
  );
}

/** Atalho direto no acervo, onde a pessoa normalmente procura para incluir uma nota. */
export function ModalImportarXmls({ aberto, aoFechar, aoConcluir }: { aberto: boolean; aoFechar: () => void; aoConcluir?: () => void }) {
  return (
    <Modal
      aberto={aberto}
      aoFechar={aoFechar}
      titulo="Importar notas"
      descricao="Selecione os XMLs ou um arquivo ZIP. As notas entram diretamente no acervo."
      largura="larga"
    >
      <ImportadorXml aoConcluir={aoConcluir} />
    </Modal>
  );
}
