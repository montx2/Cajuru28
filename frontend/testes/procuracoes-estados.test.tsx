/**
 * Vocabulário visual do módulo Procurações RFB.
 *
 * O erro que estes testes existem para impedir: pintar de vermelho um processo
 * que está apenas **esperando**. "Em análise" e "aguardando aceite" são o
 * curso normal — a Receita dá 30 dias para o outorgado validar. Vermelho ali
 * faria o operador criar uma segunda outorga para o mesmo cliente, duplicando
 * pedido no portal de terceiro.
 */
import { describe, expect, it } from "vitest";
import {
  estadoDaAutorizacao,
  estadoDaEstacao,
  estadoDoJobProcuracao,
  estadoDoPrazoAceite,
} from "@/lib/estados";
import { ROTAS, rotaDaTecla, rotaDoCaminho } from "@/lib/rotas";

describe("situação da autorização", () => {
  it("trata espera como espera, não como falha", () => {
    expect(estadoDaAutorizacao("em_analise").tom).toBe("espera");
    expect(estadoDaAutorizacao("aguardando_aceite").tom).toBe("espera");
  });

  it("marca como erro apenas o que realmente exige reação", () => {
    expect(estadoDaAutorizacao("expirada").tom).toBe("erro");
    expect(estadoDaAutorizacao("rejeitada").tom).toBe("erro");
    expect(estadoDaAutorizacao("ativa").tom).toBe("ok");
  });

  it("empresa sem autorização é neutra: é o ponto de partida, não um defeito", () => {
    expect(estadoDaAutorizacao("sem_autorizacao").tom).toBe("neutro");
  });

  it("nunca devolve rótulo vazio, mesmo para valor desconhecido", () => {
    const estado = estadoDaAutorizacao("situacao_que_nao_existe");
    expect(estado.rotulo.length).toBeGreaterThan(0);
    expect(estado.tom).toBe("neutro");
  });
});

describe("estado do job", () => {
  it("usa âmbar quando a bola está com o humano", () => {
    for (const status of [
      "pronto_para_operacao",
      "aguardando_assinatura",
      "aguardando_validacao",
      "intervencao_manual",
    ]) {
      expect(estadoDoJobProcuracao(status).tom).toBe("espera");
    }
  });

  it("pulsa apenas enquanto a máquina trabalha", () => {
    expect(estadoDoJobProcuracao("preenchendo").pulsa).toBe(true);
    expect(estadoDoJobProcuracao("aguardando_assinatura").pulsa).toBeUndefined();
    expect(estadoDoJobProcuracao("concluido").pulsa).toBeUndefined();
  });

  it("intervenção manual fala com o operador, não com o log", () => {
    expect(estadoDoJobProcuracao("intervencao_manual").rotulo).toBe("Precisa de você");
  });
});

describe("prazo do aceite", () => {
  it("vira contagem regressiva, não data crua", () => {
    expect(estadoDoPrazoAceite(12)?.rotulo).toBe("Aceite em 12d");
  });

  it("aperta o tom conforme o prazo encurta", () => {
    expect(estadoDoPrazoAceite(20)?.tom).toBe("info");
    expect(estadoDoPrazoAceite(7)?.tom).toBe("espera");
    expect(estadoDoPrazoAceite(2)?.tom).toBe("erro");
    expect(estadoDoPrazoAceite(-1)?.tom).toBe("erro");
  });

  it("sem prazo não inventa indicador", () => {
    expect(estadoDoPrazoAceite(null)).toBeNull();
  });
});

describe("estado da estação", () => {
  it("silêncio prolongado é erro, não neutro", () => {
    expect(estadoDaEstacao("offline").tom).toBe("erro");
    expect(estadoDaEstacao("online").tom).toBe("ok");
  });
});

describe("navegação", () => {
  it("registra a rota no lugar único de navegação", () => {
    const rota = rotaDoCaminho("/dashboard/procuracoes");
    expect(rota?.titulo).toBe("Procurações RFB");
    expect(rota?.grupo).toBe("Fiscal");
  });

  it("responde ao atalho g+r sem colidir com outro", () => {
    expect(rotaDaTecla("r", "admin")).toBe("/dashboard/procuracoes");
    const teclas = ROTAS.map((rota) => rota.tecla).filter(Boolean);
    expect(new Set(teclas).size).toBe(teclas.length);
  });

  it("telas internas ficam fora do menu, mas com trilha para o pai", () => {
    for (const caminho of ["/dashboard/procuracoes/empresa", "/dashboard/procuracoes/estacoes"]) {
      const rota = rotaDoCaminho(caminho);
      expect(rota?.oculta).toBe(true);
      expect(rota?.pai).toBe("/dashboard/procuracoes");
    }
  });
});
