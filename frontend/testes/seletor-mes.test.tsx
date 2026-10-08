/**
 * O seletor de competência é o único caminho para escolher o mês em Painel,
 * Documentos e Relatórios. Estes testes fixam o que o `<input type="month">`
 * nativo dava de graça e o seletor próprio precisa garantir: mês visível por
 * extenso, nenhum mês futuro clicável, teclado andando pela grade e um clique
 * levando o mês escolhido para quem chamou.
 */
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SeletorMes } from "@/components/fiscal/SeletorMes";
import { mesesDoAno, anoDe } from "@/lib/competencia";

function Controlado({ inicial = "2026-10", max = "2026-10" }: { inicial?: string; max?: string }) {
  const [mes, setMes] = useState(inicial);
  return <SeletorMes rotulo="Competência" value={mes} max={max} onChange={setMes} />;
}

describe("SeletorMes", () => {
  it("mostra a competência por extenso no gatilho e abre a grade no mês dela", async () => {
    const usuario = userEvent.setup();
    render(<Controlado />);

    const gatilho = screen.getByRole("button", { name: /competência/i });
    expect(gatilho).toHaveTextContent("outubro/2026");
    expect(gatilho).toHaveAttribute("aria-haspopup", "dialog");

    await usuario.click(gatilho);
    expect(screen.getByRole("dialog", { name: /escolher competência/i })).toBeInTheDocument();
    expect(screen.getByRole("gridcell", { name: "outubro de 2026" })).toHaveAttribute("aria-current", "date");
    expect(screen.getAllByRole("gridcell")).toHaveLength(12);
  });

  it("desabilita os meses futuros em vez de recusar depois do envio", async () => {
    const usuario = userEvent.setup();
    render(<Controlado />);
    await usuario.click(screen.getByRole("button", { name: /competência/i }));

    expect(screen.getByRole("gridcell", { name: "outubro de 2026" })).toBeEnabled();
    expect(screen.getByRole("gridcell", { name: "novembro de 2026" })).toBeDisabled();
    expect(screen.getByRole("gridcell", { name: "dezembro de 2026" })).toBeDisabled();
    // Sem teto futuro não há para onde avançar: o ano seguinte fica bloqueado.
    expect(screen.getByRole("button", { name: "Ano seguinte" })).toBeDisabled();
  });

  it("leva o mês escolhido para quem chamou e fecha a camada", async () => {
    const aoMudar = vi.fn();
    const usuario = userEvent.setup();
    render(<SeletorMes rotulo="Competência" value="2026-10" max="2026-10" onChange={aoMudar} />);

    await usuario.click(screen.getByRole("button", { name: /competência/i }));
    await usuario.click(screen.getByRole("gridcell", { name: "março de 2026" }));

    expect(aoMudar).toHaveBeenCalledWith("2026-03");
    expect(screen.queryByRole("gridcell")).not.toBeInTheDocument();
  });

  it("volta dois anos sem digitar e mantém o teclado dentro da grade", async () => {
    const usuario = userEvent.setup();
    render(<Controlado />);
    await usuario.click(screen.getByRole("button", { name: /competência/i }));

    await usuario.click(screen.getByRole("button", { name: "Ano anterior" }));
    await usuario.click(screen.getByRole("button", { name: "Ano anterior" }));
    expect(screen.getByRole("gridcell", { name: "outubro de 2024" })).toBeEnabled();
    expect(screen.getByRole("gridcell", { name: "dezembro de 2024" })).toBeEnabled();

    screen.getByRole("gridcell", { name: "janeiro de 2024" }).focus();
    await usuario.keyboard("{ArrowRight}");
    expect(screen.getByRole("gridcell", { name: "fevereiro de 2024" })).toHaveFocus();
  });
});

describe("mesesDoAno", () => {
  it("devolve os doze meses do ano com o teto aplicado", () => {
    const meses = mesesDoAno(2026, "2026-10");
    expect(meses.map((mes) => mes.valor)).toContain("2026-01");
    expect(meses.map((mes) => mes.valor)).toContain("2026-12");
    expect(meses.filter((mes) => mes.disponivel)).toHaveLength(10);
    expect(meses.find((mes) => mes.valor === "2026-11")?.disponivel).toBe(false);
  });

  it("sem teto nenhum mês fica bloqueado", () => {
    expect(mesesDoAno(2020).every((mes) => mes.disponivel)).toBe(true);
  });

  it("anoDe aceita o formato interno e cai no ano corrente quando o valor é vazio", () => {
    expect(anoDe("2019-07")).toBe(2019);
    expect(anoDe("")).toBe(new Date().getFullYear());
  });
});
