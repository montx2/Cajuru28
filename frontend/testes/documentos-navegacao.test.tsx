import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SeletorCompetencia } from "@/components/fiscal/SeletorCompetencia";
import { Combobox } from "@/components/ui/Combobox";
import { hrefComEstado } from "@/lib/urlEstadoLink";

describe("filtros do acervo de documentos", () => {
  it("mantém competência, empresa e busca ao abrir um recorte de notas", () => {
    const href = hrefComEstado(
      "/dashboard/documentos",
      "data_inicio=2026-08-01&data_fim=2026-08-31&empresa=42&busca=fornecedor&doc=17&pagina=2",
      { tipo: "nfse", mes: null, competencia: null },
      ["doc", "pagina"]
    );
    const parametros = new URL(href, "https://fluxa.local").searchParams;

    expect(parametros.get("data_inicio")).toBe("2026-08-01");
    expect(parametros.get("data_fim")).toBe("2026-08-31");
    expect(parametros.get("empresa")).toBe("42");
    expect(parametros.get("busca")).toBe("fornecedor");
    expect(parametros.get("tipo")).toBe("nfse");
    expect(parametros.has("doc")).toBe(false);
    expect(parametros.has("pagina")).toBe(false);
    expect(parametros.has("mes")).toBe(false);
  });

  it("localiza a empresa por CNPJ sem pontuação e aplica a seleção", async () => {
    const usuario = userEvent.setup();
    const aoMudar = vi.fn();
    render(
      <Combobox
        rotulo="Empresa"
        valor=""
        aoMudar={aoMudar}
        placeholder="Todas as empresas"
        opcoes={[
          { valor: "", rotulo: "Todas as empresas" },
          {
            valor: "42",
            rotulo: "EMPRESA TESTE LTDA",
            descricao: "12.345.678/0001-99 · SP",
            termosBusca: "12345678000199",
          },
        ]}
      />
    );

    const campo = screen.getByRole("combobox", { name: "Empresa" });
    await usuario.type(campo, "12345678000199");
    await usuario.click(screen.getByRole("option", { name: /EMPRESA TESTE LTDA/ }));

    expect(aoMudar).toHaveBeenCalledWith("42");
  });

  it("permite mudar de competência sem trocar de tela nem perder o estado controlado", async () => {
    const usuario = userEvent.setup();
    function SeletorControlado() {
      const [mes, setMes] = useState("2026-08");
      return <SeletorCompetencia mes={mes} aoMudar={setMes} atalhos={0} />;
    }
    render(<SeletorControlado />);

    await usuario.click(screen.getByRole("button", { name: "Competência anterior" }));

    expect(screen.getByLabelText("Competência")).toHaveValue("2026-07");
  });
});
