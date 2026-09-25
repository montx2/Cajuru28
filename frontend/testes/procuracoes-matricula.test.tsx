/**
 * Matrícula de estação ponta a ponta, pela interface.
 *
 * O defeito: a tela só tem o campo "nome" e o contrato exigia `identificador`
 * — cinco `POST /procuracoes/agentes` seguidos com 422 no log de produção, e
 * nenhuma estação jamais matriculada. O identificador passou a ser gerado pelo
 * servidor; a tela manda só o nome e exibe o que voltou, inclusive a linha de
 * comando do instalador.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Estacoes } from "@/app/dashboard/procuracoes/estacoes/Estacoes";
import { ProvedorToast } from "@/components/ui/Toast";

const IDENTIFICADOR = "9f2c7b1a4d6e8035a1b2c3d4e5f60718";

const matricularAgente = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    agentesProcuracao: vi.fn().mockResolvedValue([]),
    requisitosAgente: vi.fn().mockResolvedValue({ passos: [], url_manual: "", url_teste: "" }),
    matricularAgente: (...args: unknown[]) => matricularAgente(...args),
    revogarAgente: vi.fn(),
  },
  ApiError: class extends Error {
    status = 0;
    problemas: unknown[] = [];
  },
}));

vi.mock("@/components/shell/ProvedorSessao", () => ({
  useSessao: () => ({ somenteLeitura: false, papel: "admin", ehAdmin: true }),
}));

function montar() {
  return render(
    <ProvedorToast>
      <Estacoes />
    </ProvedorToast>
  );
}

describe("matricular estação", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    matricularAgente.mockResolvedValue({
      agente: { id: 1, identificador: IDENTIFICADOR, nome: "PC Fiscal 01", situacao: "offline" },
      segredo: "segredo-de-uso-unico-1234567890",
      aviso: "Copie agora: este segredo não será exibido novamente.",
    });
  });

  it("envia só o nome — a tela não tem, nem precisa ter, identificador", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.click(screen.getByRole("button", { name: /matricular estação/i }));
    await usuario.type(screen.getByLabelText(/nome da estação/i), "PC Fiscal 01");
    await usuario.click(screen.getByRole("button", { name: /gerar credencial/i }));

    await waitFor(() => expect(matricularAgente).toHaveBeenCalledTimes(1));
    expect(matricularAgente).toHaveBeenCalledWith("PC Fiscal 01");
  });

  it("mostra o identificador gerado pelo servidor e o comando do instalador", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.click(screen.getByRole("button", { name: /matricular estação/i }));
    await usuario.type(screen.getByLabelText(/nome da estação/i), "PC Fiscal 01");
    await usuario.click(screen.getByRole("button", { name: /gerar credencial/i }));

    await screen.findByText(/segredo de uso único/i);
    // O identificador aparece duas vezes: para copiar e dentro do comando do
    // instalar_agent.ps1, que é onde ele será usado de fato.
    const ocorrencias = screen.getAllByText((_, elemento) =>
      Boolean(elemento?.textContent?.includes(IDENTIFICADOR))
    );
    expect(ocorrencias.length).toBeGreaterThan(0);
    const comando = document.querySelector("pre");
    expect(comando?.textContent).toContain("instalar_agent.ps1");
    expect(comando?.textContent).toContain(IDENTIFICADOR);
  });

  it("sem nome, não deixa gerar credencial", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.click(screen.getByRole("button", { name: /matricular estação/i }));
    expect(screen.getByRole("button", { name: /gerar credencial/i })).toBeDisabled();
    expect(matricularAgente).not.toHaveBeenCalled();
  });
});
