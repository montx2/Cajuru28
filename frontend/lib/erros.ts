import { ApiError, type ProblemaValidacao } from "./api";
import type { Tom } from "./estados";

/**
 * Nome do campo como o operador o vê na tela. O contrato usa `snake_case`;
 * mostrar "base_url" numa mensagem de erro é jogar o vocabulário do banco na
 * cara de quem só quer saber onde clicar.
 */
const ROTULO_DO_CAMPO: Record<string, string> = {
  base_url: "Base URL",
  segredo: "Credencial",
  identificador: "Identificador",
  fonte: "Fonte",
  texto: "Lista colada",
  situacao_padrao: "Situação da aba",
  nome: "Nome",
  outorgado_documento: "CNPJ/CPF da contabilidade",
  alerta_dias: "Janelas de alerta",
  arquivo: "Arquivo",
  data_inicio: "Data inicial",
  data_fim: "Data final",
  competencia: "Competência",
};

export function rotuloDoCampo(campo: string): string {
  const limpo = campo.trim();
  if (!limpo) return "";
  const conhecido = ROTULO_DO_CAMPO[limpo];
  if (conhecido) return conhecido;
  return limpo
    .split(" → ")
    .map((parte) => parte.replace(/_/g, " "))
    .join(" → ")
    .replace(/^./, (letra) => letra.toUpperCase());
}

/**
 * Campos recusados pela API, para a tela destacar o que precisa de conserto.
 * Vazio quando o erro não é de validação.
 */
export function problemasDeValidacao(erro: unknown): ProblemaValidacao[] {
  return erro instanceof ApiError ? erro.problemas : [];
}

export interface ErroDescrito {
  titulo: string;
  /** O que provavelmente causou — sem achismo vago. */
  causa: string;
  /** O próximo passo concreto do operador. */
  proximoPasso: string;
  /** Janela/cota é espera: âmbar, nunca vermelho. */
  tom: Tom;
  detalhe?: string;
}

/**
 * Toda mensagem de erro do produto passa por aqui: o que aconteceu, por que e
 * qual o próximo passo. "Tente novamente" sozinho não é mensagem — é ruído.
 */
export function descreverErro(erro: unknown, contexto = "carregar estes dados"): ErroDescrito {
  if (erro instanceof ApiError) {
    switch (erro.status) {
      case 0:
        return {
          titulo: "A API não respondeu",
          causa: `Nenhuma resposta veio do endereço configurado (${erro.message.match(/em (.+?)\./)?.[1] ?? "mesma origem"}). Em geral é o contêiner da API parado ou a rede interna fora do ar.`,
          proximoPasso: "Rode `docker compose ps` e confira `GET /saude`. Quando a API voltar, use Tentar novamente.",
          tom: "erro",
          detalhe: erro.message,
        };
      case 401:
        return {
          titulo: "Sessão expirada",
          causa: "O cookie de sessão perdeu a validade e a API recusou a chamada.",
          proximoPasso: "Entre novamente com as credenciais do escritório.",
          tom: "espera",
        };
      case 403:
        return {
          titulo: "Ação não permitida para esta sessão",
          causa: "Ou a origem da requisição não está na lista permitida (proteção contra CSRF), ou o seu papel não inclui esta ação.",
          proximoPasso: "Confirme se está usando o endereço oficial do sistema e, se precisar da ação, peça a um administrador.",
          tom: "erro",
          detalhe: erro.message,
        };
      case 404:
        return {
          titulo: "Registro não encontrado",
          causa: `O recurso pedido para ${contexto} não existe mais — pode ter sido removido em outra aba.`,
          proximoPasso: "Atualize a lista e repita a consulta.",
          tom: "erro",
          detalhe: erro.message,
        };
      case 413:
        return {
          titulo: "Arquivo acima do limite",
          causa: "O envio passou de 35 MiB, que é o teto aceito pela API.",
          proximoPasso: "Divida o lote em arquivos menores e envie de novo.",
          tom: "erro",
          detalhe: erro.message,
        };
      case 422: {
        // O 422 do Pydantic sempre diz qual campo e por quê. Antes esta
        // resposta era descartada e a tela mostrava um texto fixo sobre
        // "período e competência" — inútil em formulário que não tem período,
        // e foi o que fez o operador tentar a mesma credencial cinco vezes.
        const campos = erro.problemas.filter((item) => item.mensagem);
        if (campos.length === 1) {
          const [problema] = campos;
          const rotulo = rotuloDoCampo(problema.campo);
          return {
            titulo: rotulo ? `Campo recusado: ${rotulo}` : "Dado recusado pela API",
            causa: problema.mensagem,
            proximoPasso: rotulo
              ? `Ajuste "${rotulo}" e envie novamente.`
              : "Ajuste o dado informado e envie novamente.",
            tom: "erro",
            detalhe: erro.message,
          };
        }
        if (campos.length > 1) {
          return {
            titulo: `${campos.length} campos recusados`,
            causa: campos
              .map((item) => `${rotuloDoCampo(item.campo) || "campo"}: ${item.mensagem}`)
              .join(" · "),
            proximoPasso: `Corrija ${campos
              .map((item) => rotuloDoCampo(item.campo) || "o campo indicado")
              .join(", ")} e envie novamente.`,
            tom: "erro",
            detalhe: erro.message,
          };
        }
        return {
          titulo: "A API recusou os parâmetros",
          causa:
            erro.message ||
            "Algum filtro obrigatório está ausente ou em formato diferente do esperado (período em AAAA-MM-DD, competência em MM/AAAA).",
          proximoPasso: "Confira o período e os filtros destacados abaixo e envie novamente.",
          tom: "erro",
          detalhe: erro.message,
        };
      }
      case 429:
        return {
          titulo: "Consulta na janela oficial da SEFAZ",
          causa: "A API limitou a chamada porque o mesmo CNPJ e tipo já foi consultado há menos de uma hora — é o intervalo oficial, não uma falha.",
          proximoPasso: "Não é preciso fazer nada: o agendador retoma sozinho na hora certa.",
          tom: "espera",
          detalhe: erro.message,
        };
      default:
        if (erro.status >= 500) {
          return {
            titulo: "Falha interna na API",
            causa: `O servidor respondeu ${erro.status} ao ${contexto}.`,
            proximoPasso: "Tente novamente; se persistir, veja os detalhes em Saúde do sistema e o log do contêiner `api`.",
            tom: "erro",
            detalhe: erro.message,
          };
        }
        return {
          titulo: "Não foi possível concluir",
          causa: erro.message,
          proximoPasso: "Tente novamente ou ajuste os filtros da consulta.",
          tom: "erro",
          detalhe: erro.message,
        };
    }
  }

  return {
    titulo: "Falha inesperada",
    causa: erro instanceof Error ? erro.message : String(erro),
    proximoPasso: "Tente novamente. Se repetir, anote a hora exata e confira o log do contêiner `api`.",
    tom: "erro",
  };
}

/**
 * Frase para avisos flutuantes: título + próximo passo, sem o detalhe técnico
 * (esse fica na tela de erro, onde há espaço para ele).
 *
 * Exceção deliberada: em erro de validação a **causa** é a informação que
 * resolve ("a URL precisa começar com https://"). Omiti-la transformava o
 * aviso em ruído — o operador lia "confira os campos" sem saber qual.
 */
export function mensagemDoErro(erro: unknown, contexto?: string): string {
  const descrito = descreverErro(erro, contexto);
  const ehValidacao = erro instanceof ApiError && erro.status === 422 && erro.problemas.length > 0;
  const partes = ehValidacao ? [descrito.causa, descrito.proximoPasso] : [descrito.proximoPasso];
  return [`${descrito.titulo}.`, ...partes.filter(Boolean)].join(" ");
}
