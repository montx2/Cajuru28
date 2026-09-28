"use client";

/**
 * Importação de XMLs prontos — ZIP ou arquivos soltos exportados de outro
 * sistema (Jettax360, e-mail, pasta do computador).
 *
 * Este caminho **não gasta cota da SEFAZ**: é para o escritório que deixa
 * outro sistema com a consulta automática (dois robôs no mesmo certificado
 * geram 656, consumo indevido). As notas chegam como arquivo e são gravadas
 * no mesmo acervo, sem duplicar.
 */

import { useState } from "react";
import { api } from "@/lib/api";
import { numero, plural } from "@/lib/format";
import { mensagemDoErro } from "@/lib/erros";
import { ROTULO_TIPO, type ImportacaoXmlResposta } from "@/lib/types";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { useToast } from "@/components/ui/Toast";
import { Cartao } from "@/components/ui/Cartao";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { Botao } from "@/components/ui/Botao";
import { Dado } from "@/components/ui/Dado";
import { Cnpj } from "@/components/ui/Formatadores";
import { Etiqueta } from "@/components/ui/Etiqueta";

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

export function ImportarXmls() {
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
    <Cartao
      titulo="Importar XMLs do computador"
      descricao="ZIP ou arquivos .xml exportados de outro sistema (ex.: Jettax360). Não gasta cota da SEFAZ — a nota é lida do próprio arquivo."
      rodape={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-tinta-suave">
            {resultado
              ? "Importação concluída — revise os itens abaixo."
              : "O XML é casado com a empresa pelo CNPJ do destinatário (ou do emitente, quando é nota prestada)."}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Botao
              variante="primaria"
              onClick={enviar}
              carregando={enviando}
              disabled={!podeEnviar}
              title={
                somenteLeitura
                  ? "Seu papel é somente leitura"
                  : arquivos.length === 0
                    ? "Escolha um .zip ou arquivos .xml"
                    : undefined
              }
            >
              Importar XMLs
            </Botao>
          </div>
        </div>
      }
    >
      <div className="space-y-4">
        {erro ? <p className="text-sm text-erro">{erro}</p> : null}

        {resultado ? (
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

            <div className="rolagem-fina max-h-80 overflow-y-auto rounded-cartao border border-traco">
              <table className="w-full text-sm">
                <caption className="sr-only">Arquivos processados</caption>
                <thead className="sticky top-0 bg-superficie-alta">
                  <tr className="border-b border-traco text-left text-2xs uppercase tracking-[.04em] text-tinta-suave">
                    <th scope="col" className="px-3 py-2 font-medium">Arquivo</th>
                    <th scope="col" className="px-3 py-2 font-medium">Empresa</th>
                    <th scope="col" className="px-3 py-2 font-medium">Situação</th>
                    <th scope="col" className="px-3 py-2 font-medium">Mensagem</th>
                  </tr>
                </thead>
                <tbody>
                  {resultado.itens.map((item, indice) => (
                    <tr key={`${item.chave}-${indice}`} className="border-b border-traco last:border-0">
                      <td className="px-3 py-2 text-xs text-tinta-suave">
                        {item.origem}
                        {item.tipo ? (
                          <span className="ml-1 text-tinta-fraca">· {ROTULO_TIPO[item.tipo as keyof typeof ROTULO_TIPO] ?? item.tipo}</span>
                        ) : null}
                      </td>
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        <span className="block truncate text-tinta">{item.razao_social || "—"}</span>
                        {item.cnpj_cpf ? (
                          <Cnpj valor={item.cnpj_cpf} copiar={false} className="text-xs text-tinta-suave" />
                        ) : null}
                      </th>
                      <td className="px-3 py-2">
                        <Etiqueta tom={TOM_DO_STATUS[item.status] ?? "neutro"}>
                          {ROTULO_STATUS[item.status] ?? item.status}
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
        ) : (
          <CampoArquivo
            rotulo="ZIP ou XMLs exportados"
            aceita=".zip,.xml"
            multiplo
            arquivos={arquivos}
            aoMudar={setArquivos}
            maxBytes={100 * 1024 * 1024}
            descricao="Pode anexar um .zip com tudo dentro ou os .xml soltos. Até 200 XMLs por lote; cada XML de até 2 MB."
          />
        )}
      </div>
    </Cartao>
  );
}
