import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FiltrosAcervoDocumentos } from "@/components/fiscal/FiltrosAcervoDocumentos";

describe("filtros rápidos do acervo fiscal", () => {
  it("mantém tipo e operação independentes para combinar notas de serviço tomadas ou prestadas", async () => {
    const usuario = userEvent.setup();
    const aoMudarTipo = vi.fn();
    const aoMudarDirecao = vi.fn();
    render(
      <FiltrosAcervoDocumentos
        tipo="nfse"
        direcao="tomada"
        aoMudarTipo={aoMudarTipo}
        aoMudarDirecao={aoMudarDirecao}
        filtroAtivo={false}
        aoLimpar={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "NFS-e · serviço" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Entrada / tomada" })).toHaveAttribute("aria-pressed", "true");

    await usuario.click(screen.getByRole("button", { name: "Saída / prestada" }));
    expect(aoMudarDirecao).toHaveBeenCalledWith("prestada");
    expect(aoMudarTipo).not.toHaveBeenCalled();

    await usuario.click(screen.getByRole("button", { name: "NF-e" }));
    expect(aoMudarTipo).toHaveBeenCalledWith("nfe");
    expect(aoMudarDirecao).toHaveBeenCalledTimes(1);
  });

  it("remove só a dimensão escolhida ao selecionar todas", async () => {
    const usuario = userEvent.setup();
    const aoMudarTipo = vi.fn();
    const aoMudarDirecao = vi.fn();
    render(
      <FiltrosAcervoDocumentos
        tipo="nfe"
        direcao="prestada"
        aoMudarTipo={aoMudarTipo}
        aoMudarDirecao={aoMudarDirecao}
        filtroAtivo={true}
        aoLimpar={vi.fn()}
      />
    );

    await usuario.click(screen.getByRole("button", { name: "Todos os tipos" }));
    expect(aoMudarTipo).toHaveBeenCalledWith(null);
    expect(aoMudarDirecao).not.toHaveBeenCalled();

    await usuario.click(screen.getByRole("button", { name: "Todas" }));
    expect(aoMudarDirecao).toHaveBeenCalledWith(null);
  });

  it("oferece uma ação visível para limpar todos os filtros ativos", async () => {
    const usuario = userEvent.setup();
    const aoLimpar = vi.fn();
    render(
      <FiltrosAcervoDocumentos
        tipo="nfse"
        direcao="prestada"
        aoMudarTipo={vi.fn()}
        aoMudarDirecao={vi.fn()}
        filtroAtivo
        aoLimpar={aoLimpar}
      />
    );

    await usuario.click(screen.getByRole("button", { name: "Limpar todos os filtros" }));
    expect(aoLimpar).toHaveBeenCalledOnce();
  });
});
