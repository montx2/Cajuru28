/**
 * O lote que importou 203 certificados com "ICP-Brasil" no lugar da razão
 * social: a tela precisa dizer quantas empresas entraram sem nome e oferecer o
 * conserto pelo cadastro do escritório (Acessórias) ou pela Receita — sem
 * reenviar arquivo nenhum.
 */
import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModalImportacaoLote } from "@/app/dashboard/empresas/Empresas";
import { ProvedorToast } from "@/components/ui/Toast";

const importarEmpresasEmMassa = vi.fn();
const completarCadastrosEmpresas = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    importarEmpresasEmMassa: (...args: unknown[]) => importarEmpresasEmMassa(...args),
    completarCadastrosEmpresas: (...args: unknown[]) => completarCadastrosEmpresas(...args),
    listarEmpresas: vi.fn().mockResolvedValue([]),
  },
  ApiError: class extends Error {
    status = 0;
    problemas: unknown[] = [];
  },
}));

vi.mock("@/components/shell/ProvedorSessao", () => ({
  useSessao: () => ({ usuario: { id: 1, nome: "Admin" }, somenteLeitura: false, papel: "admin", ehAdmin: true }),
}));

const PFX = () => new File([new Uint8Array([1, 2, 3, 4])], "12345678000195.pfx", { type: "application/octet-stream" });

async function importar(usuario: ReturnType<typeof userEvent.setup>) {
  const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
  await usuario.upload(campoCertificados, PFX());
  await usuario.click(screen.getByRole("button", { name: /importar lote/i }));
  await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
}

describe("empresas sem razão social no resultado do lote", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("mostra o aviso com a contagem e o botão de completar", async () => {
    importarEmpresasEmMassa.mockResolvedValue({
      total: 203,
      criadas: 203,
      certificados: 203,
      ja_existiam: 0,
      erros: 0,
      itens: [],
      empresas_sem_nome: 20,
    });
    const usuario = userEvent.setup();
    montar();

    await importar(usuario);

    expect(await screen.findByText(/20 empresas entraram sem razão social/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /completar nomes agora/i })).toBeInTheDocument();
  });

  it("um clique completa pelo Acessórias e depois pela Receita", async () => {
    importarEmpresasEmMassa.mockResolvedValue({
      total: 203,
      criadas: 203,
      certificados: 203,
      ja_existiam: 0,
      erros: 0,
      itens: [],
      empresas_sem_nome: 20,
    });
    completarCadastrosEmpresas.mockResolvedValue({
      analisadas: 20,
      corrigidas: 18,
      uf_completada: 3,
      sem_fonte: 2,
      acessorias_configurado: true,
      itens: [],
    });
    const usuario = userEvent.setup();
    montar();

    await importar(usuario);
    await usuario.click(screen.getByRole("button", { name: /completar nomes agora/i }));

    await waitFor(() => expect(completarCadastrosEmpresas).toHaveBeenCalledTimes(1));
    expect(completarCadastrosEmpresas).toHaveBeenCalledWith({ reconsultar: true });
    expect(await screen.findByText(/18 razões sociais corrigidas/i)).toBeInTheDocument();
    expect(screen.getByText(/2 sem cadastro em nenhuma fonte/i)).toBeInTheDocument();
  });

  it("lote com todos os nomes resolvidos não promete nada", async () => {
    importarEmpresasEmMassa.mockResolvedValue({
      total: 2,
      criadas: 2,
      certificados: 2,
      ja_existiam: 0,
      erros: 0,
      itens: [],
      empresas_sem_nome: 0,
    });
    const usuario = userEvent.setup();
    montar();

    await importar(usuario);

    expect(screen.queryByText(/sem razão social/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /completar nomes agora/i })).not.toBeInTheDocument();
    expect(completarCadastrosEmpresas).not.toHaveBeenCalled();
  });
});

function montar() {
  return render(
    <ProvedorToast>
      <ModalImportacaoLote aberto aoFechar={() => {}} aoImportar={() => {}} />
    </ProvedorToast>
  );
}
