import type { Tom } from "./estados";
import { contagem, numero } from "./format";
import type { ResultadoImportacaoSelecionada } from "./types";

/**
 * O aviso (toast) do disparo de captura.
 *
 * O texto não pode depender só de "quantas foram enfileiradas": quando a fila
 * do próprio Fluxa está fora do ar, `enfileiradas` é 0 e `aguardando` é 0, e o
 * operador lia "Nada a fazer neste recorte" — como se o recorte estivesse vazio,
 * quando o problema era a fila. A leitura certa vem do motivo de cada item.
 *
 * Prioridade das manchetes: falha local da fila (é ação de infraestrutura, e o
 * operador precisa saber que o clique não valeu) > captura enfileirada >
 * janela em espera > cadastro pendente > recorte vazio.
 */
export interface AvisoDisparo {
  tom: Tom;
  titulo: string;
  descricao: string;
}

export function avisoDoDisparo(
  resultado: ResultadoImportacaoSelecionada,
  rotuloDoPeriodo: string,
): AvisoDisparo {
  const descricao = `${numero(resultado.aguardando)} aguardando · ${numero(resultado.ignoradas)} ignoradas · ${rotuloDoPeriodo}`;
  const semFila = resultado.itens.filter((item) => item.status === "fila_indisponivel").length;
  const semCadastro = resultado.itens.filter(
    (item) => item.status === "sem_certificado" || item.status === "sem_uf",
  ).length;

  if (semFila > 0) {
    return {
      tom: "erro",
      titulo: "A fila de processamento não respondeu",
      descricao:
        `${numero(resultado.enfileiradas)} enfileiradas · ` +
        `${contagem(semFila, "captura não saiu", "capturas não saíram")}: ` +
        "nada foi consultado na SEFAZ. Confira os serviços de fila e worker e dispare de novo. " +
        `· ${descricao}`,
    };
  }

  if (resultado.enfileiradas > 0) {
    return {
      tom: "ok",
      titulo: contagem(resultado.enfileiradas, "captura enfileirada", "capturas enfileiradas"),
      descricao,
    };
  }

  if (resultado.aguardando > 0) {
    return { tom: "espera", titulo: "Nada enfileirado: há janelas em espera", descricao };
  }

  if (semCadastro > 0) {
    return {
      tom: "erro",
      titulo: "Nada foi disparado: falta cadastro",
      descricao:
        `${contagem(semCadastro, "empresa está sem certificado A1 ou sem UF", "empresas estão sem certificado A1 ou sem UF")} — ` +
        `nada foi consultado na SEFAZ. · ${descricao}`,
    };
  }

  return { tom: "info", titulo: "Nada a fazer neste recorte", descricao };
}
