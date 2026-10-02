import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "@/components/shell/Sidebar";

const mocks = vi.hoisted(() => ({ caminho: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.caminho }));
vi.mock("@/components/shell/ProvedorSessao", () => ({ useSessao: () => ({ papel: "admin", usuario: { escritorio_nome: "Escritório de teste" } }) }));
vi.mock("@/components/shell/ProvedorAlertas", () => ({ useContagemAlertas: () => ({ contagem: { total: 0, criticos: 0, atencao: 0 } }) }));

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => vi.unstubAllGlobals());

const props = { aberta: false, colapsada: false, aoFechar: vi.fn(), aoAlternarColapso: vi.fn() };

describe("navegação sem estados ambíguos", () => {
  it.each([
    ["/dashboard", "Painel"],
    ["/dashboard/documentos", "Documentos"],
    ["/dashboard/empresas", "Empresas"],
    ["/dashboard/empresa", "Empresas"],
    ["/dashboard/procuracoes/empresa", "Procurações RFB"],
  ])("marca uma única rota em %s", (caminho, rotulo) => {
    mocks.caminho = caminho;
    render(<Sidebar {...props} />);
    const ativos = screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page");
    expect(ativos).toHaveLength(1);
    expect(ativos[0]).toHaveTextContent(rotulo);
  });

  it("o menu mobile continua completo mesmo com o desktop recolhido", async () => {
    const usuario = userEvent.setup();
    const fechar = vi.fn();
    render(<Sidebar {...props} aberta colapsada aoFechar={fechar} />);
    const menu = screen.getByRole("dialog", { name: "Menu de navegação" });
    expect(menu.querySelector(".lateral-colapsada")).toBeNull();
    expect(within(menu).getByRole("link", { name: "Empresas" })).toHaveTextContent("Empresas");
    await usuario.click(within(menu).getByRole("button", { name: "Fechar menu" }));
    expect(fechar).toHaveBeenCalledOnce();
  });
});
