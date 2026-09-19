import { ApiError } from "./api";
import type { Tom } from "./estados";

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
      case 422:
        return {
          titulo: "A API recusou os parâmetros",
          causa: "Algum filtro obrigatório está ausente ou em formato diferente do esperado (período em AAAA-MM-DD, competência em MM/AAAA).",
          proximoPasso: "Confira o período e os filtros destacados abaixo e envie novamente.",
          tom: "erro",
          detalhe: erro.message,
        };
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
          // Um 5xx com `detail` curado pela API (ex.: diagnóstico da Jettax)
          // não é "falha interna": a mensagem explica a recusa e o que fazer.
          // Escondê-la atrás do texto genérico deixava o operador sem a única
          // pista acionável. O fallback sem detail continua genérico e seguro.
          const mensagemApi = erro.message.trim();
          const recusadaExplicada = mensagemApi !== "" && mensagemApi !== "Erro inesperado na API";
          if (recusadaExplicada) {
            return {
              titulo: "O servidor recusou a ação",
              causa: `O servidor respondeu ${erro.status} ao ${contexto} e explicou o motivo.`,
              proximoPasso: mensagemApi,
              tom: "erro",
              detalhe: mensagemApi,
            };
          }
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
 * Frase curta para avisos flutuantes: título + próximo passo, sem o detalhe
 * técnico (esse fica na tela de erro, onde há espaço para ele).
 */
export function mensagemDoErro(erro: unknown, contexto?: string): string {
  const descrito = descreverErro(erro, contexto);
  return `${descrito.titulo}. ${descrito.proximoPasso}`;
}
