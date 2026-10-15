import { describe, expect, it } from "vitest";
import { janelaDeCancelamento, jornadaDoDocumento } from "@/lib/estados";

/**
 * Jornada da nota: emissão → captura → ciência → XML (→ cancelamento).
 *
 * A etapa da Ciência só existe nas tomadas (a empresa é destinatária); nas
 * prestadas ela some em vez de ficar "pendente para sempre".
 */
describe("jornadaDoDocumento", () => {
  it("monta as 4 etapas da tomada com XML completo", () => {
    const etapas = jornadaDoDocumento({
      data_emissao: "2026-10-10T10:07:39-03:00",
      direcao: "tomada",
      importado_em: "2026-10-11T05:55:54-03:00",
      manifestado_em: "2026-10-11T06:00:00-03:00",
      leiaute: "completo",
      status: "normal",
    });
    expect(etapas.map((etapa) => etapa.codigo)).toEqual(["emissao", "captura", "ciencia", "xml"]);
    expect(etapas.every((etapa) => etapa.estado === "feita")).toBe(true);
  });

  it("marca a ciência como falha quando a SEFAZ recusou", () => {
    const etapas = jornadaDoDocumento({
      data_emissao: "2026-10-10T10:07:39-03:00",
      direcao: "tomada",
      importado_em: "2026-10-11T05:55:54-03:00",
      manifestacao_erro: "596: evento fora do prazo",
      leiaute: "resumo",
      status: "normal",
    });
    expect(etapas.find((etapa) => etapa.codigo === "ciencia")?.estado).toBe("falha");
    expect(etapas.find((etapa) => etapa.codigo === "xml")?.estado).toBe("pendente");
  });

  it("pula a ciência nas prestadas e fecha com o cancelamento", () => {
    const etapas = jornadaDoDocumento({
      data_emissao: "2026-10-10T10:07:39-03:00",
      direcao: "prestada",
      importado_em: "2026-10-11T05:55:54-03:00",
      leiaute: "completo",
      status: "cancelada",
      cancelado_em: "2026-10-11T08:00:00-03:00",
      motivo_cancelamento: "Erro de digitação",
    });
    expect(etapas.map((etapa) => etapa.codigo)).toEqual(["emissao", "captura", "xml", "cancelamento"]);
    expect(etapas.at(-1)?.detalhe).toBe("Erro de digitação");
  });
});

describe("janelaDeCancelamento", () => {
  it("abre 24 h a partir da emissão e depois encerra", () => {
    const emissao = new Date("2026-10-10T10:00:00-03:00").getTime();
    const dentro = janelaDeCancelamento("2026-10-10T10:00:00-03:00", emissao + 23 * 3_600_000);
    expect(dentro.aberta).toBe(true);
    expect(dentro.restaMs).toBe(3_600_000);
    const fora = janelaDeCancelamento("2026-10-10T10:00:00-03:00", emissao + 25 * 3_600_000);
    expect(fora.aberta).toBe(false);
    expect(fora.restaMs).toBe(0);
  });
});
