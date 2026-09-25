/**
 * Credencial de integração: aceitar o que é válido, recusar o que não é —
 * dizendo o que corrigir antes de gastar uma ida ao servidor.
 *
 * A única integração remota do módulo é o SERPRO Integra Contador. A lista do
 * Jettax 360 entra por importação (colagem/CSV), sem credencial — o
 * formulário antigo de "Base URL + credencial do Jettax" deixou de existir,
 * e o teste garante que ele não volte por engano.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfiguracaoProcuracoes } from "@/app/dashboard/procuracoes/ConfiguracaoProcuracoes";
import { ProvedorToast } from "@/components/ui/Toast";

const salvarIntegracaoProcuracao = vi.fn();
const testarIntegracaoProcuracao = vi.fn();
const sincronizarProcuracoes = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    configuracaoProcuracoes: vi.fn().mockResolvedValue({
      dias_alerta_vencimento: 30,
      dias_alerta_aceite: 7,
      sincronizacao_automatica: false,
      hora_sincronizacao: 6,
    }),
    integracoesProcuracao: vi.fn().mockResolvedValue([
      {
        fonte: "integra_contador",
        rotulo: "Integra Contador (SERPRO)",
        base_url: "",
        identificador: "",
        configurado: true,
        ativo: true,
        opcoes: {},
        ultima_utilizacao_em: null,
        ultimo_erro: "",
        atualizado_em: null,
      },
    ]),
    modelosProcuracao: vi.fn().mockResolvedValue([]),
    salvarConfiguracaoProcuracoes: vi.fn(),
    salvarIntegracaoProcuracao: (...args: unknown[]) => salvarIntegracaoProcuracao(...args),
    testarIntegracaoProcuracao: (...args: unknown[]) => testarIntegracaoProcuracao(...args),
    sincronizarProcuracoes: (...args: unknown[]) => sincronizarProcuracoes(...args),
  },
  ApiError: class extends Error {
    status = 0;
    problemas: unknown[] = [];
  },
}));

vi.mock("@/components/shell/ProvedorSessao", () => ({
  useSessao: () => ({ usuario: { id: 1, nome: "Admin" }, somenteLeitura: false, papel: "admin", ehAdmin: true }),
}));

function montar() {
  return render(
    <ProvedorToast>
      <ConfiguracaoProcuracoes aberta aoFechar={() => {}} aoSalvar={() => {}} />
    </ProvedorToast>
  );
}

const TOKEN = "token-de-integracao-1234";

describe("credencial de integração", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    salvarIntegracaoProcuracao.mockResolvedValue({});
    testarIntegracaoProcuracao.mockResolvedValue({
      fonte: "integra_contador",
      ok: true,
      mensagem: "Conexão estabelecida com o Integra Contador.",
    });
    sincronizarProcuracoes.mockResolvedValue({ mensagem: "Nada a atualizar." });
  });

  it("grava só o token do Integra Contador — sem endereço, sem Jettax", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(await screen.findByLabelText(/token do integra contador/i), TOKEN);
    await usuario.click(screen.getByRole("button", { name: /gravar credencial/i }));

    await waitFor(() => expect(salvarIntegracaoProcuracao).toHaveBeenCalledTimes(1));
    expect(salvarIntegracaoProcuracao).toHaveBeenCalledWith({
      fonte: "integra_contador",
      segredo: TOKEN,
    });
    // O formulário de endereço do Jettax não existe mais.
    expect(screen.queryByLabelText(/base url/i)).toBeNull();
    expect(screen.queryByText(/jettax 360/i, { selector: "option" })).toBeNull();
  });

  it("diz quantos caracteres faltam no token curto, sem chamar a API", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(await screen.findByLabelText(/token do integra contador/i), "curto");

    expect(screen.getByText(/Faltam 3 caractere/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /gravar credencial/i })).toBeDisabled();
    expect(salvarIntegracaoProcuracao).not.toHaveBeenCalled();
  });

  it("testa a integração e mostra a mensagem devolvida (não um campo inexistente)", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.click(await screen.findByRole("button", { name: /^testar$/i }));

    await waitFor(() => expect(testarIntegracaoProcuracao).toHaveBeenCalledWith("integra_contador"));
    expect(await screen.findByText(/Conexão estabelecida com o Integra Contador/i)).toBeInTheDocument();
  });

  it("sincroniza apontando para a única fonte remota", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.click(await screen.findByRole("button", { name: /^sincronizar$/i }));

    await waitFor(() => expect(sincronizarProcuracoes).toHaveBeenCalledWith("integra_contador"));
  });

  it("avisa que a lista do Jettax entra por importação, sem credencial", async () => {
    montar();
    expect(await screen.findByText(/entra por importação/i)).toBeInTheDocument();
    expect(screen.getByText(/não publica API de procurações/i)).toBeInTheDocument();
    expect(screen.getByText(/não guarda credencial de terceiro/i)).toBeInTheDocument();
  });
});
