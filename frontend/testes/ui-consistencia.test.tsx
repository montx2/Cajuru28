import { useState } from "react";
import { renderToString } from "react-dom/server";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Abas, PainelAbas } from "@/components/ui/Abas";
import { Entrada } from "@/components/ui/Campo";
import { Botao } from "@/components/ui/Botao";
import { BotaoIcone } from "@/components/ui/BotaoIcone";
import { Icone } from "@/components/ui/Icone";
import { MenuSuspenso } from "@/components/ui/MenuSuspenso";
import { Modal } from "@/components/ui/Modal";
import { Popover } from "@/components/ui/Popover";
import { BarraProgresso } from "@/components/ui/Progresso";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { ProvedorAgora, useAgora } from "@/components/shell/ProvedorAgora";
import { ProvedorProgresso, useProgresso } from "@/components/shell/BarraAtualizacao";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("controles e camadas consistentes", () => {
  it("mantém o nome e o conteúdo do botão durante o carregamento", () => {
    const acao = vi.fn();
    const { rerender } = render(<Botao onClick={acao}>Salvar</Botao>);
    const botao = screen.getByRole("button", { name: "Salvar" });
    expect(botao).toHaveClass("botao-controle");
    rerender(<Botao onClick={acao} carregando>Salvar</Botao>);
    expect(botao).toHaveAttribute("aria-busy", "true");
    expect(botao).toBeDisabled();
    expect(botao).toHaveAccessibleName("Salvar");
    fireEvent.click(botao);
    expect(acao).not.toHaveBeenCalled();
  });

  it("não acumula alturas conflitantes no botão de ícone compacto", () => {
    render(<BotaoIcone tamanho="sm" rotulo="Atualizar" icone={<Icone nome="atualizar" />} />);
    const botao = screen.getByRole("button", { name: "Atualizar" });
    expect(botao).toHaveClass("botao-controle", "botao-sm", "botao-icone");
    expect(botao.className).not.toMatch(/\bh-(8|9|10|11)\b/);
  });

  it("abre o menu fora do overflow, aceita cliques no portal e devolve foco com Escape", async () => {
    const usuario = userEvent.setup();
    const acao = vi.fn();
    const { container } = render(<div style={{ overflow: "hidden" }}><MenuSuspenso rotulo="Ações" itens={[{ id: "copiar", rotulo: "Copiar", aoClicar: acao }]} /></div>);
    const gatilho = screen.getByRole("button", { name: "Ações" });
    await usuario.click(gatilho);
    const menu = screen.getByRole("menu", { name: "Ações" });
    expect(container).not.toContainElement(menu);
    expect(menu.closest("section")).toHaveAttribute("aria-label", "Ações");
    expect(menu.closest("section")?.parentElement).toBe(document.body);
    await usuario.click(screen.getByRole("menuitem", { name: "Copiar" }));
    expect(acao).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await usuario.click(gatilho);
    await usuario.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(gatilho).toHaveFocus();
  });

  it("Escape fecha o menu dentro do modal sem fechar também o formulário", async () => {
    function Formulario() {
      const [aberto, setAberto] = useState(true);
      return <Modal aberto={aberto} aoFechar={() => setAberto(false)} titulo="Formulário"><MenuSuspenso rotulo="Opções" itens={[{ id: "opcao", rotulo: "Uma opção" }]} /></Modal>;
    }
    const usuario = userEvent.setup();
    render(<Formulario />);
    await usuario.click(screen.getByRole("button", { name: "Opções" }));
    await usuario.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Formulário" })).toBeInTheDocument();
    await usuario.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("mostra o rótulo completo quando o popover não é só ícone", async () => {
    const usuario = userEvent.setup();
    render(<Popover rotulo="Filtros de documentos">{() => <p>Filtros disponíveis</p>}</Popover>);
    const gatilho = screen.getByRole("button", { name: "Filtros de documentos" });
    expect(gatilho).not.toHaveClass("botao-icone");
    await usuario.click(gatilho);
    expect(screen.getByRole("dialog", { name: "Filtros de documentos" })).toHaveTextContent("Filtros disponíveis");
  });

  it("permite percorrer filtros no portal e sair com Tab para o controle seguinte", async () => {
    const usuario = userEvent.setup();
    render(<><Popover rotulo="Filtros">{(fechar) => <><Entrada rotulo="Valor" /><Botao onClick={fechar}>Aplicar</Botao></>}</Popover><Botao>Próximo controle</Botao></>);
    await usuario.click(screen.getByRole("button", { name: "Filtros" }));
    const entrada = screen.getByRole("textbox", { name: "Valor" });
    expect(entrada).toHaveFocus();
    await usuario.type(entrada, "123");
    expect(entrada).toHaveValue("123");
    expect(entrada).toHaveFocus();
    await usuario.tab();
    expect(screen.getByRole("button", { name: "Aplicar" })).toHaveFocus();
    await usuario.tab();
    expect(screen.queryByRole("dialog", { name: "Filtros" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Próximo controle" })).toHaveFocus();
  });

  it("ações junto a campos de preferência têm semântica e foco de diálogo", async () => {
    const usuario = userEvent.setup();
    render(<MenuSuspenso rotulo="Preferências" tipo="dialog" itens={[{ id: "mostrar", rotulo: "Mostrar todas" }]}><label><input type="checkbox" />Coluna</label></MenuSuspenso>);
    const gatilho = screen.getByRole("button", { name: "Preferências" });
    expect(gatilho).toHaveAttribute("aria-haspopup", "dialog");
    await usuario.click(gatilho);
    expect(screen.getByRole("dialog", { name: "Preferências" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Coluna" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await usuario.keyboard("{Escape}");
    expect(gatilho).toHaveFocus();
  });

  it("expõe o limite correto na barra de progresso", () => {
    render(<BarraProgresso valor={8} maximo={20} rotulo="Captura" />);
    expect(screen.getByRole("progressbar", { name: "Captura" })).toHaveAttribute("aria-valuemax", "20");
  });
});

describe("tabela legível por padrão", () => {
  const colunas: ColunaTabela<{ nome: string }>[] = [
    { id: "nome", cabecalho: "Empresa", fixa: true, celula: (linha) => linha.nome },
    { id: "normal", cabecalho: "Situação", celula: () => "Ativa" },
    { id: "tecnica", cabecalho: "Dado técnico", ocultaPorPadrao: true, celula: () => "Interno" },
  ];
  const props = { colunas, linhas: [{ nome: "Empresa de teste" }], chaveDaLinha: () => 1, legenda: "Empresas", estados: { vazioTitulo: "Sem dados" } };

  it("respeita colunas ocultas sem perder a possibilidade de mostrá-las", () => {
    const { rerender } = render(<Tabela {...props} />);
    expect(screen.getByRole("columnheader", { name: "Empresa" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Situação" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Dado técnico" })).not.toBeInTheDocument();
    rerender(<Tabela {...props} colunasVisiveis={["tecnica"]} />);
    expect(screen.getByRole("columnheader", { name: "Empresa" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Dado técnico" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Situação" })).not.toBeInTheDocument();
  });
});

it("relógios do shell têm uma primeira renderização determinística no servidor", () => {
  function Leitura() {
    const agora = useAgora();
    const { ultimaAtualizacao } = useProgresso();
    return <span data-agora={agora} data-atualizacao={ultimaAtualizacao}>Relógio</span>;
  }
  const html = renderToString(<ProvedorAgora><ProvedorProgresso><Leitura /></ProvedorProgresso></ProvedorAgora>);
  expect(html).toContain('data-agora="0"');
  expect(html).toContain('data-atualizacao="0"');
});

it("liga todas as abas a painéis existentes sem montar o conteúdo inativo", async () => {
  const usuario = userEvent.setup();
  const abas = [{ valor: "cadastro", rotulo: "Cadastro" }, { valor: "historico", rotulo: "Histórico" }];
  function Secoes() {
    const [valor, setValor] = useState("cadastro");
    return <><Abas abas={abas} idBase="secoes" valor={valor} aoMudar={setValor} rotulo="Seções" /><PainelAbas abas={abas} idBase="secoes" valor={valor}><p>{valor}</p></PainelAbas></>;
  }
  render(<Secoes />);
  for (const aba of screen.getAllByRole("tab")) expect(document.getElementById(aba.getAttribute("aria-controls")!)).toBeInTheDocument();
  expect(screen.getByRole("tabpanel", { name: "Cadastro" })).toHaveTextContent("cadastro");
  expect(screen.queryByRole("tabpanel", { name: "Histórico" })).not.toBeInTheDocument();
  await usuario.click(screen.getByRole("tab", { name: "Histórico" }));
  expect(screen.getByRole("tabpanel", { name: "Histórico" })).toHaveTextContent("historico");
});

it("filtros segmentados não anunciam painéis inexistentes", () => {
  render(<Abas modo="filtros" idBase="nivel" rotulo="Nível" abas={[{ valor: "", rotulo: "Todos" }]} valor="" aoMudar={vi.fn()} />);
  expect(screen.getByRole("group", { name: "Nível" })).toBeInTheDocument();
  const todos = screen.getByRole("button", { name: "Todos" });
  expect(todos).toHaveAttribute("aria-pressed", "true");
  expect(todos).not.toHaveAttribute("aria-controls");
});

it("mede linhas maiores sem quebrar os espaçadores da tabela virtualizada", () => {
  const observadores: { callback: ResizeObserverCallback; elementos: Set<Element> }[] = [];
  vi.stubGlobal("ResizeObserver", class {
    registro: typeof observadores[number];
    constructor(callback: ResizeObserverCallback) {
      this.registro = { callback, elementos: new Set() };
      observadores.push(this.registro);
    }
    observe(elemento: Element) { this.registro.elementos.add(elemento); }
    disconnect() {}
  });
  const linhas = Array.from({ length: 500 }, (_, id) => ({ id, nome: `Empresa ${id}` }));
  const { container } = render(<Tabela linhas={linhas} chaveDaLinha={(linha) => linha.id} colunas={[{ id: "nome", cabecalho: "Empresa", celula: (linha) => linha.nome }]} legenda="Empresas" densidade="compacta" estados={{ vazioTitulo: "Sem dados" }} />);
  const medidor = observadores.filter((observador) => Array.from(observador.elementos).some((elemento) => elemento.tagName === "TR")).at(-1)!;
  const linha = Array.from(medidor.elementos)[0];
  Object.defineProperty(linha, "offsetHeight", { configurable: true, value: 53 });
  act(() => medidor.callback([{ target: linha } as ResizeObserverEntry], {} as ResizeObserver));
  const visiveis = container.querySelectorAll<HTMLTableRowElement>("tbody tr[data-linha]");
  expect(visiveis.length).toBeGreaterThan(0);
  visiveis.forEach((elemento) => expect(elemento.style.height).toBe("53px"));
  const espaco = container.querySelector<HTMLTableRowElement>("tbody tr[aria-hidden='true']")!;
  expect(parseFloat(espaco.style.height)).toBe((linhas.length - visiveis.length) * 53);
});
