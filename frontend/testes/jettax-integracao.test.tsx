import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JettaxIntegracao } from "@/app/dashboard/configuracoes/JettaxIntegracao";
import { ProvedorToast } from "@/components/ui/Toast";

const mocks = vi.hoisted(() => ({
  statusJettax: vi.fn(), listarEmpresas: vi.fn(), execucoesJettax: vi.fn(),
  salvarCredencialJettax: vi.fn(), testarJettax: vi.fn(), removerCredencialJettax: vi.fn(), importarJettax: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: mocks }));

function montar(admin = true, somenteLeitura = false) {
  return render(<ProvedorToast><JettaxIntegracao admin={admin} somenteLeitura={somenteLeitura} /></ProvedorToast>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.statusJettax.mockResolvedValue({ configurado: true, base_url: "https://morfeu.jettax360.com.br" });
  mocks.listarEmpresas.mockResolvedValue([{ id: 1, razao_social: "Empresa Teste", ativa: true }]);
  mocks.execucoesJettax.mockResolvedValue([]);
  mocks.salvarCredencialJettax.mockResolvedValue({ configurado: true });
  mocks.importarJettax.mockResolvedValue([]);
});

describe("integração Jettax NFS-e", () => {
  it("salva e limpa token sem exibir token anterior", async () => {
    const usuario = userEvent.setup();
    montar();
    await screen.findByText(/Token configurado no cofre/);
    const campo = screen.getByLabelText("Token Jettax");
    expect(campo).toHaveAttribute("type", "password");
    expect(campo).toHaveValue("");
    await usuario.type(campo, "segredo-local");
    await usuario.click(screen.getByRole("button", { name: "Salvar token Jettax" }));
    await waitFor(() => expect(mocks.salvarCredencialJettax).toHaveBeenCalledWith("segredo-local"));
    await waitFor(() => expect(campo).toHaveValue(""));
  });

  it("envia empresas e competência e mostra resultados por empresa", async () => {
    const usuario = userEvent.setup();
    montar();
    await screen.findByRole("option", { name: "Empresa Teste" });
    await usuario.selectOptions(screen.getByLabelText("Empresa para importar"), "1");
    await usuario.type(screen.getByLabelText("Competência Jettax"), "08/2026");
    await usuario.click(screen.getByRole("button", { name: "Importar do Jettax" }));
    await waitFor(() => expect(mocks.importarJettax).toHaveBeenCalledWith([1], "08/2026"));
  });

  it("perfil leitura não altera token nem importa", async () => {
    montar(false, true);
    await screen.findByText(/Token configurado no cofre/);
    expect(screen.getByLabelText("Token Jettax")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Salvar token Jettax" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Importar do Jettax" })).toBeDisabled();
  });
});
