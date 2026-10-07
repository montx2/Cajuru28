import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";

interface Linha {
  id: number;
  nome: string;
}

const LINHAS: Linha[] = [
  { id: 1, nome: "Documento um" },
  { id: 2, nome: "Documento dois" },
];

const COLUNAS: Array<ColunaTabela<Linha>> = [
  { id: "nome", cabecalho: "Nome", celula: (linha) => linha.nome },
];

function TabelaControlada() {
  const [selecionadas, setSelecionadas] = useState(new Set<string>());

  return (
    <Tabela
      linhas={LINHAS}
      colunas={COLUNAS}
      chaveDaLinha={(linha) => linha.id}
      legenda="Documentos"
      estados={{ vazioTitulo: "Nenhum documento" }}
      ferramentas={<button type="button">Ferramentas padrão</button>}
      selecao={{ chaves: selecionadas, aoMudar: setSelecionadas, totalNoFiltro: LINHAS.length }}
      barraDeSelecao={({ quantidade }) => <button type="button">Baixar {quantidade} XML</button>}
    />
  );
}

function TabelaComSelecaoDoFiltro() {
  const [selecionadas, setSelecionadas] = useState(new Set<string>());
  const [todasDoFiltro, setTodasDoFiltro] = useState(false);

  return (
    <Tabela
      linhas={LINHAS}
      colunas={COLUNAS}
      chaveDaLinha={(linha) => linha.id}
      legenda="Documentos"
      estados={{ vazioTitulo: "Nenhum documento" }}
      ferramentas={<button type="button">Ferramentas padrão</button>}
      selecao={{
        chaves: selecionadas,
        aoMudar: (proximas) => {
          setTodasDoFiltro(false);
          setSelecionadas(proximas);
        },
        totalNoFiltro: 3,
        aoSelecionarTudoDoFiltro: () => {
          setSelecionadas(new Set());
          setTodasDoFiltro(true);
        },
        todasDoFiltro,
        aoCancelarTudoDoFiltro: () => {
          setTodasDoFiltro(false);
          setSelecionadas(new Set());
        },
      }}
      barraDeSelecao={({ quantidade }) => <button type="button">Baixar {quantidade} XML</button>}
    />
  );
}

describe("barra contextual da tabela", () => {
  it("substitui as ferramentas padrão enquanto há linhas selecionadas", async () => {
    const usuario = userEvent.setup();
    render(<TabelaControlada />);

    expect(screen.getByRole("button", { name: "Ferramentas padrão" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Baixar 1 XML/i })).not.toBeInTheDocument();

    await usuario.click(screen.getByRole("checkbox", { name: "Selecionar linha 1" }));

    expect(screen.queryByRole("button", { name: "Ferramentas padrão" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Baixar 1 XML" })).toBeInTheDocument();
    expect(screen.getByText("1 selecionada")).toBeInTheDocument();

    await usuario.click(screen.getByRole("button", { name: "Limpar seleção" }));

    expect(screen.getByRole("button", { name: "Ferramentas padrão" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Baixar 1 XML/i })).not.toBeInTheDocument();
  });

  it("oferece todas as linhas do filtro, mesmo além das linhas carregadas", async () => {
    const usuario = userEvent.setup();
    render(<TabelaComSelecaoDoFiltro />);

    await usuario.click(screen.getByRole("checkbox", { name: "Selecionar linha 1" }));
    await usuario.click(screen.getByRole("button", { name: "Selecionar todas as 3 do filtro" }));

    expect(screen.getByText("Todas as 3 do filtro")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Baixar 3 XML" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Selecionar todas as linhas desta página" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Selecionar linha 1" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Selecionar linha 2" })).toBeChecked();
  });
});
