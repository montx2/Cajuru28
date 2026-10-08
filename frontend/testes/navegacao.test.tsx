import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProvedorComandos } from "@/components/shell/ProvedorComandos";
import { Sidebar } from "@/components/shell/Sidebar";
import { ATALHOS, ROTAS_DO_PREFIXO_G } from "@/lib/atalhos";
import { ROTAS, rotaDaTecla, rotaVisivel, rotasDoMenu } from "@/lib/rotas";

const mocks = vi.hoisted(() => ({
  caminho: "/dashboard",
  empurrar: vi.fn(),
  listarEmpresas: vi.fn().mockResolvedValue([]),
  listarDocumentos: vi.fn().mockResolvedValue([]),
}));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.caminho, useRouter: () => ({ push: mocks.empurrar }) }));
vi.mock("@/lib/api", () => ({ api: { listarEmpresas: mocks.listarEmpresas, listarDocumentos: mocks.listarDocumentos } }));
vi.mock("@/components/shell/ProvedorSessao", () => ({ useSessao: () => ({ papel: "admin", usuario: { escritorio_nome: "Escritório de teste" } }) }));
vi.mock("@/components/shell/ProvedorAlertas", () => ({ useContagemAlertas: () => ({ contagem: { total: 0, criticos: 0, atencao: 0 } }) }));

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  mocks.listarEmpresas.mockResolvedValue([]);
  mocks.listarDocumentos.mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

const props = { aberta: false, colapsada: false, aoFechar: vi.fn(), aoAlternarColapso: vi.fn() };

describe("navegação sem estados ambíguos", () => {
  it("usa o mesmo registro no menu e mantém mapa de atalhos coerente", () => {
    expect(ROTAS).toHaveLength(13);
    expect(rotasDoMenu("admin")).toHaveLength(12);
    expect(ROTAS_DO_PREFIXO_G).not.toHaveProperty("r");
    expect(rotaDaTecla("r", "admin")).toBeUndefined();
    expect(ROTAS.find((rota) => rota.tecla === "r")).toBeUndefined();

    const atalhosDeNavegacao = ATALHOS.filter((atalho) => atalho.grupo === "Navegação");
    expect(atalhosDeNavegacao).toHaveLength(Object.keys(ROTAS_DO_PREFIXO_G).length);
    expect(atalhosDeNavegacao.map((atalho) => atalho.teclas[1].toLowerCase()).sort()).toEqual(
      Object.keys(ROTAS_DO_PREFIXO_G).sort()
    );
  });

  it("abre a paleta real com Ctrl+K e lista apenas rotas do registro", async () => {
    render(
      <ProvedorComandos>
        <div>Conteúdo principal</div>
      </ProvedorComandos>
    );
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    const paleta = await screen.findByRole("dialog", { name: "Paleta de comandos" });
    const secaoNavegacao = within(paleta).getByRole("heading", { name: "Navegação" }).closest("section");
    const opcoes = within(secaoNavegacao!).getAllByRole("option");
    const rotasDaPaleta = ROTAS.filter((rota) => rotaVisivel(rota, "admin"));

    expect(opcoes).toHaveLength(rotasDaPaleta.length);
    expect(opcoes.map((opcao) => opcao.querySelector("span > span")?.textContent)).toEqual(
      rotasDaPaleta.map((rota) => rota.titulo)
    );
  });

  it.each([
    ["/dashboard", "Painel"],
    ["/dashboard/documentos", "Documentos"],
    ["/dashboard/empresas", "Empresas"],
    ["/dashboard/empresa", "Empresas"],
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
