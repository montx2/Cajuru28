import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SeletorEmpresas } from "@/components/fiscal/SeletorEmpresas";
import type { EstadoVisual } from "@/lib/estados";
import type { Empresa } from "@/lib/types";

/* A lista de empresas é a tela que mais erra por largura: nome longo + CNPJ +
 * situação não cabem em qualquer janela. Estes testes prendem as duas pontas:
 * o comportamento (busca, marcar todas as visíveis, intervalo com Shift) e o
 * contrato de largura — nenhum controle pode empurrar o cartão para fora da
 * coluna que o contém. */

function empresa(id: number, razao_social: string, cnpj_cpf: string, ativa = true): Empresa {
  return { id, razao_social, cnpj_cpf, uf: "MG", ativa, criado_em: "2026-01-05T09:00:00-03:00" };
}

const EMPRESAS: Empresa[] = [
  empresa(1, "WS SPORTS COMERCIO DE ARTIGOS ESPORTIVOS LTDA", "48979197000189"),
  empresa(2, "IMOBILIARIA PEDROSA LTDA", "00585041000197"),
  empresa(3, "DOCE TEMPERO ALIMENTACAO INDUSTRIAL LTDA", "00796329000100"),
  empresa(4, "ZENAIDE GOMES DA SILVA LTDA", "02555674000188"),
  empresa(5, "PRISMINAS CERTIFICACAO DIGITAL LTDA", "03049033000114", false),
];

/** Espelho do contrato controlado: a tela guarda a seleção e devolve via URL. */
const SITUACOES: Map<number, EstadoVisual> = new Map([
  [1, { tom: "acento", rotulo: "Varrendo agora", icone: "atualizar", pulsa: true }],
  [2, { tom: "ok", rotulo: "Em dia", icone: "verificar-circulo" }],
  [5, { tom: "neutro", rotulo: "Nunca consultado", icone: "relogio" }],
]);

function Espelho({
  empresas = EMPRESAS,
  iniciais = [],
  bloqueios,
  desabilitadas,
}: {
  empresas?: Empresa[];
  iniciais?: number[];
  bloqueios?: Map<number, string>;
  desabilitadas?: Set<number>;
}) {
  const [selecionadas, setSelecionadas] = useState<Set<number>>(new Set(iniciais));
  return (
    <SeletorEmpresas
      empresas={empresas}
      selecionadas={selecionadas}
      aoMudar={setSelecionadas}
      situacoes={SITUACOES}
      bloqueios={bloqueios}
      desabilitadas={desabilitadas}
      altura={320}
    />
  );
}

function caixaDaEmpresa(nome: string) {
  return screen.getByRole("checkbox", { name: `Selecionar ${nome}` });
}

describe("seletor de empresas", () => {
  it("marca e desmarca pela caixa da linha", async () => {
    const usuario = userEvent.setup();
    render(<Espelho />);

    const caixa = caixaDaEmpresa("IMOBILIARIA PEDROSA LTDA");
    expect(caixa).not.toBeChecked();
    await usuario.click(caixa);
    expect(caixa).toBeChecked();
    await usuario.click(caixa);
    expect(caixa).not.toBeChecked();
  });

  it("mostra a contagem em vez de repetir o nome da lista", () => {
    render(<Espelho iniciais={[1, 3]} />);
    const linha = screen.getByText(/de 5 marcadas/);
    expect(linha).toHaveTextContent("2 de 5 marcadas");
    // O nome da lista vai só para leitor de tela: o cartão já o imprime acima.
    const paraLeitor = screen.getByText("Empresas:");
    expect(paraLeitor).toHaveClass("sr-only");
  });

  it("prende a largura ao contêiner em vez de estourar o cartão", () => {
    const { container } = render(<Espelho />);
    const cartao = container.firstElementChild as HTMLElement;
    expect(cartao).toHaveClass("min-w-0", "overflow-hidden", "rounded-cartao");

    const lista = screen.getByRole("group", { name: /empresas listadas/ });
    expect(lista).toHaveClass("overflow-y-auto", "overflow-x-hidden");

    // A busca pode encolher: a base larga com `min-width` fixa empurrava o
    // cartão para fora da coluna em janelas estreitas.
    const busca = screen.getByRole("searchbox", { name: /Buscar empresa/ });
    expect(busca.className).not.toMatch(/min-w-48/);
    expect(busca.parentElement?.className).not.toMatch(/min-w-48/);
  });

  it("trunca a situação da linha em vez de vazar pela borda", () => {
    render(
      <Espelho
        iniciais={[1]}
        bloqueios={new Map([[2, "Sem certificado A1"]])}
        desabilitadas={new Set([2])}
        empresas={EMPRESAS}
      />
    );
    const situacao = screen.getByText("Varrendo agora");
    expect(situacao).toHaveClass("truncate");
    const celula = situacao.closest("[class*='w-40']");
    expect(celula?.className).toMatch(/w-28|w-36|w-40/);
    expect(celula?.className).toMatch(/flex-none/);
  });

  it("busca por razão social e por CNPJ", async () => {
    const usuario = userEvent.setup();
    render(<Espelho />);

    const busca = screen.getByRole("searchbox", { name: /Buscar empresa/ });
    await usuario.type(busca, "doce");
    expect(caixaDaEmpresa("DOCE TEMPERO ALIMENTACAO INDUSTRIAL LTDA")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /IMOBILIARIA PEDROSA/ })).not.toBeInTheDocument();

    await usuario.clear(busca);
    await usuario.type(busca, "03049033000114");
    expect(caixaDaEmpresa("PRISMINAS CERTIFICACAO DIGITAL LTDA")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /WS SPORTS/ })).not.toBeInTheDocument();
  });

  it("marca todas as visíveis respeitando o filtro da busca", async () => {
    const usuario = userEvent.setup();
    render(<Espelho />);

    const todas = screen.getByRole("checkbox", { name: /Selecionar todas as 5 visíveis/ });
    await usuario.click(todas);
    expect(screen.getByText(/5 de 5 marcadas/)).toBeInTheDocument();
    await usuario.click(todas);
    expect(screen.getByText(/0 de 5 marcadas/)).toBeInTheDocument();

    await usuario.type(screen.getByRole("searchbox", { name: /Buscar empresa/ }), "ltda");
    const visiveis = screen.getByRole("checkbox", { name: /Selecionar todas as 5 visíveis/ });
    await usuario.click(visiveis);
    expect(screen.getByText(/5 de 5 marcadas/)).toBeInTheDocument();
  });

  it("não marca as visíveis quando a lista está vazia", async () => {
    const usuario = userEvent.setup();
    render(<Espelho />);
    await usuario.type(screen.getByRole("searchbox", { name: /Buscar empresa/ }), "zzz");
    expect(screen.getByText("Nenhuma empresa corresponde ao filtro.")).toBeInTheDocument();
    const todas = screen.getByRole("checkbox", { name: /Selecionar todas as 0 visíveis/ });
    expect(todas).toBeDisabled();
  });

  it("marca o intervalo com Shift a partir da última clicada", () => {
    render(<Espelho />);
    fireEvent.click(caixaDaEmpresa("IMOBILIARIA PEDROSA LTDA"));
    fireEvent.click(caixaDaEmpresa("ZENAIDE GOMES DA SILVA LTDA"), { shiftKey: true });

    expect(caixaDaEmpresa("WS SPORTS COMERCIO DE ARTIGOS ESPORTIVOS LTDA")).not.toBeChecked();
    expect(caixaDaEmpresa("IMOBILIARIA PEDROSA LTDA")).toBeChecked();
    expect(caixaDaEmpresa("DOCE TEMPERO ALIMENTACAO INDUSTRIAL LTDA")).toBeChecked();
    expect(caixaDaEmpresa("ZENAIDE GOMES DA SILVA LTDA")).toBeChecked();
  });

  it("bloqueia a linha sem certificado e explica o motivo", () => {
    const motivo = vi.fn(() => "Sem certificado A1");
    render(<Espelho bloqueios={new Map([[1, "Sem certificado A1"]])} desabilitadas={new Set([1])} />);
    const caixa = caixaDaEmpresa("WS SPORTS COMERCIO DE ARTIGOS ESPORTIVOS LTDA");
    expect(caixa).toBeDisabled();
    expect(caixa).toHaveAttribute("title", motivo());
    expect(within(caixa.closest("li") as HTMLElement).getByText("Sem certificado A1", { selector: ".sr-only" })).toBeInTheDocument();
    // Empresa inativa não entra na captura mesmo sem bloqueio explícito.
    expect(caixaDaEmpresa("PRISMINAS CERTIFICACAO DIGITAL LTDA")).toBeDisabled();
  });

  it("avisa quando não há empresa cadastrada", () => {
    render(<Espelho empresas={[]} />);
    expect(screen.getByText("Nenhuma empresa cadastrada.")).toBeInTheDocument();
  });
});
