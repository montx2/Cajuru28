import { describe, expect, it } from "vitest";
import { contagem, dataHora, instante, plural, tempoRelativo } from "@/lib/format";

/**
 * Regressões dos itens A1 e A6 da auditoria.
 *
 * A1: `plural()` devolvia "9 pendências" e 32 chamadas somavam um `numero()`
 *     próprio — a tela mostrava "9 9 pendências". `plural()` agora devolve só
 *     a palavra; o número vem de `contagem()`.
 * A6: a API grava UTC e, sem offset no texto, `new Date` lia como hora local —
 *     em Brasília (UTC-3) um registro de agora aparecia no futuro.
 */
describe("plural e contagem (A1)", () => {
  it("plural devolve só a palavra, sem o número", () => {
    expect(plural(1, "documento")).toBe("documento");
    expect(plural(2, "documento")).toBe("documentos");
    expect(plural(1, "pendência", "pendências")).toBe("pendência");
    expect(plural(9, "pendência", "pendências")).toBe("pendências");
  });

  it("contagem devolve o número uma única vez", () => {
    expect(contagem(1, "documento")).toBe("1 documento");
    expect(contagem(12, "documento")).toBe("12 documentos");
    expect(contagem(1127, "documento")).toBe("1.127 documentos");
    expect(contagem(1, "usuário", "usuários")).toBe("1 usuário");
    expect(contagem(2, "usuário", "usuários")).toBe("2 usuários");
  });

  it("nunca duplica o número em frases compostas", () => {
    const frase = `${contagem(9, "pendência", "pendências")} em aberto · ${contagem(1, "crítico", "críticos")}`;
    expect(frase).toBe("9 pendências em aberto · 1 crítico");
    expect(frase).not.toMatch(/\b9 9\b/);
  });
});

describe("datas sem offset são UTC (A6)", () => {
  const semOffset = "2026-10-08T10:44:44";

  it("instante trata ISO sem offset como UTC", () => {
    expect(instante(semOffset).getTime()).toBe(Date.parse("2026-10-08T10:44:44Z"));
  });

  it("instante mantém offset explícito como veio", () => {
    expect(instante("2026-10-08T10:44:44-03:00").getTime()).toBe(Date.parse("2026-10-08T10:44:44-03:00"));
    expect(instante("2026-10-08T10:44:44+00:00").getTime()).toBe(Date.parse("2026-10-08T10:44:44Z"));
  });

  it("data civil (AAAA-MM-DD) continua ao meio-dia local, sem perder o dia", () => {
    const data = instante("2026-10-08");
    expect(data.getFullYear()).toBe(2026);
    expect(data.getMonth()).toBe(9);
    expect(data.getDate()).toBe(8);
  });

  it("'há quanto tempo' não joga o registro para o futuro", () => {
    // 20 s depois do registro: ainda "agora" (o limiar é 45 s).
    expect(tempoRelativo(semOffset, Date.parse("2026-10-08T10:45:04Z"))).toBe("agora");
    // 50 s depois: passado, nunca "em 50 s".
    const logoDepois = tempoRelativo(semOffset, Date.parse("2026-10-08T10:45:34Z"));
    expect(logoDepois).toBe("há 50 s");
    expect(logoDepois).not.toMatch(/^em /);
    // 3 h depois o registro continua no passado — com o bug do fuso, aparecia "em 3 h".
    expect(tempoRelativo(semOffset, Date.parse("2026-10-08T13:44:44Z"))).toBe("há 3 h");
  });

  it("dataHora mostra o instante UTC, não o deslocado pelo fuso local", () => {
    expect(dataHora(semOffset)).toBe(dataHora("2026-10-08T10:44:44Z"));
  });
});
