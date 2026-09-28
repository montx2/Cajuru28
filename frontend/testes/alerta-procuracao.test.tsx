/**
 * A fila de atenção precisa levar o clique ao lugar certo — inclusive para o
 * módulo de Procurações, que antes vivia só na própria tela.
 */
import { describe, expect, it } from "vitest";
import { destinoDoAlerta, rotuloDaAcao } from "@/components/fiscal/CartaoAlerta";
import type { AlertaItem } from "@/lib/types";

function alerta(parcial: Partial<AlertaItem>): AlertaItem {
  return {
    id: "x",
    nivel: "atencao",
    categoria: "procuracao",
    titulo: "Outorga esperando você",
    detalhe: "",
    empresa_id: null,
    empresa_razao_social: null,
    acao_rotulo: null,
    acao_href: null,
    ...parcial,
  };
}

describe("alerta de procuração", () => {
  it("sem ação específica, a categoria leva à tela de Procurações", () => {
    expect(destinoDoAlerta(alerta({}))).toBe("/dashboard/procuracoes");
    expect(rotuloDaAcao(alerta({}))).toBe("Resolver");
  });

  it("alerta de processo leva ao painel do próprio job", () => {
    const item = alerta({ acao_href: "/dashboard/procuracoes?job=42", acao_rotulo: "Abrir processo" });
    expect(destinoDoAlerta(item)).toBe("/dashboard/procuracoes?job=42");
    expect(rotuloDaAcao(item)).toBe("Abrir processo");
  });
});
