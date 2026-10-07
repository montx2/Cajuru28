import { describe, expect, it } from "vitest";
import {
  filtrosParaBaixarSelecao,
  filtrosParaBaixarTudoDoFiltro,
} from "@/lib/exportacao-documentos";

describe("download da seleção de documentos", () => {
  it("preserva notas canceladas e os XMLs incompletos escolhidos", () => {
    const filtros = filtrosParaBaixarSelecao(
      {
        empresa_id: 42,
        data_inicio: "2026-09-01",
        data_fim: "2026-09-30",
      },
      [17, 23]
    );

    expect(filtros).toMatchObject({
      empresa_id: 42,
      data_inicio: "2026-09-01",
      data_fim: "2026-09-30",
      documento_ids: "17,23",
      incluir_canceladas: true,
      incluir_incompletos: true,
    });
  });

  it("usa o filtro inteiro sem excluir canceladas ao selecionar todas as linhas", () => {
    expect(
      filtrosParaBaixarTudoDoFiltro({
        data_inicio: "2026-09-01",
        data_fim: "2026-09-30",
      })
    ).toEqual({
      data_inicio: "2026-09-01",
      data_fim: "2026-09-30",
      incluir_canceladas: true,
      incluir_incompletos: true,
    });
  });
});
