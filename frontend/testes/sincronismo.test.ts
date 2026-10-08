import { describe, expect, it } from "vitest";
import { rotuloProximaVarredura } from "@/lib/sincronismo";

describe("próxima varredura automática", () => {
  it("não exibe um contador quando a automação está desligada, mesmo com tick antigo", () => {
    expect(
      rotuloProximaVarredura(true, "2026-10-08T12:10:00Z", Date.parse("2026-10-08T12:00:00Z"))
    ).toMatch(/^em /);
    expect(
      rotuloProximaVarredura(false, "2026-10-08T12:10:00Z", Date.parse("2026-10-08T12:00:00Z"))
    ).toBe("não programada");
  });

  it("mostra um traço se a automação está ligada, mas ainda não recebeu horário", () => {
    expect(rotuloProximaVarredura(true, null, Date.parse("2026-10-08T12:00:00Z"))).toBe("—");
  });
});
