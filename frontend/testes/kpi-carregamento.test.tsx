/**
 * O KPI é o número que conduz a leitura do Painel, do Fechamento e do acervo.
 * Estes testes fixam a diferença entre as duas cargas: sem número ainda, o
 * esqueleto é honesto; com número na tela, a recarga esmaece o valor em vez de
 * trocá-lo por um retângulo cinza — o operador não pode perder o dado que está
 * lendo a cada troca de filtro.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Kpi } from "@/components/ui/Kpi";

describe("Kpi", () => {
  it("na primeira carga mostra o esqueleto no lugar do número", () => {
    const { container } = render(<Kpi rotulo="Documentos" valor="1.127" carregando />);

    expect(container.querySelector(".esqueleto")).not.toBeNull();
    expect(screen.queryByText("1.127")).not.toBeInTheDocument();
  });

  it("na recarga mantém o número, esmaecido e anunciado como ocupado", () => {
    const { container } = render(<Kpi rotulo="Documentos" valor="1.127" atualizando />);

    expect(container.querySelector(".esqueleto")).toBeNull();
    const numero = screen.getByText("1.127");
    expect(numero).toBeInTheDocument();
    expect(numero.closest("[aria-busy='true']")).not.toBeNull();
  });

  it("mês em andamento: variação visível, tom neutro e rótulo próprio", () => {
    const { container } = render(
      <Kpi rotulo="Documentos em outubro/2026" valor="129" variacao={{ valor: -76, base: "vs. mês anterior", parcial: true }} />
    );

    const variacao = screen.getByText("-76,0%");
    expect(variacao).toBeInTheDocument();
    expect(screen.getByText("mês em andamento")).toBeInTheDocument();
    expect(variacao.closest("p")?.className).toContain("text-tinta-suave");
    expect(container.textContent).not.toContain("text-erro");
  });

  it("mês fechado: queda continua lida como queda", () => {
    render(<Kpi rotulo="Documentos" valor="90" variacao={{ valor: -12, base: "vs. mês anterior" }} />);

    const variacao = screen.getByText("-12,0%");
    expect(variacao.closest("p")?.className).toContain("text-erro");
    expect(screen.queryByText("mês em andamento")).not.toBeInTheDocument();
  });
});
