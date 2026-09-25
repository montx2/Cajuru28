/**
 * Credencial de integração: aceitar o que é válido, recusar o que não é —
 * dizendo o que corrigir antes de gastar uma ida ao servidor.
 *
 * O defeito: `PUT /procuracoes/integracoes` respondia 422 para
 * `admin.jettax360.com.br` (sem esquema) e para segredo curto, e a tela
 * mostrava "confira os filtros da consulta". As regras do contrato agora estão
 * espelhadas aqui, no formulário.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfiguracaoProcuracoes } from "@/app/dashboard/procuracoes/ConfiguracaoProcuracoes";
import { ProvedorToast } from "@/components/ui/Toast";

const salvarIntegracaoProcuracao = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    configuracaoProcuracoes: vi.fn().mockResolvedValue({
      dias_alerta_vencimento: 30,
      dias_alerta_aceite: 7,
      sincronizacao_automatica: false,
      hora_sincronizacao: 6,
    }),
    integracoesProcuracao: vi.fn().mockResolvedValue([
      { fonte: "jettax360", base_url: "", configurada: false, ultima_sincronizacao: null, ultimo_erro: null },
    ]),
    modelosProcuracao: vi.fn().mockResolvedValue([]),
    salvarConfiguracaoProcuracoes: vi.fn(),
    salvarIntegracaoProcuracao: (...args: unknown[]) => salvarIntegracaoProcuracao(...args),
    testarIntegracaoProcuracao: vi.fn(),
    sincronizarProcuracoes: vi.fn(),
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
      <ConfiguracaoProcuracoes aberta aoFechar={() => {}} aoSalvar={() => {}} />
    </ProvedorToast>
  );
}

const SEGREDO = "token-de-integracao-1234";

describe("credencial de integração", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    salvarIntegracaoProcuracao.mockResolvedValue({});
  });

  it("aceita URL https com segredo completo", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(await screen.findByLabelText(/base url/i), "https://admin.jettax360.com.br");
    await usuario.type(screen.getByLabelText(/credencial/i), SEGREDO);
    await usuario.click(screen.getByRole("button", { name: /gravar credencial/i }));

    await waitFor(() => expect(salvarIntegracaoProcuracao).toHaveBeenCalledTimes(1));
    expect(salvarIntegracaoProcuracao).toHaveBeenCalledWith({
      fonte: "jettax360",
      base_url: "https://admin.jettax360.com.br",
      segredo: SEGREDO,
    });
  });

  it("completa o https:// do endereço copiado da barra do navegador", async () => {
    const usuario = userEvent.setup();
    montar();

    const campo = await screen.findByLabelText(/base url/i);
    await usuario.type(campo, "admin.jettax360.com.br");
    await usuario.tab();

    await waitFor(() => expect(campo).toHaveValue("https://admin.jettax360.com.br"));
  });

  it("recusa http:// dizendo por quê, sem chamar a API", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(await screen.findByLabelText(/base url/i), "http://admin.jettax360.com.br");
    await usuario.type(screen.getByLabelText(/credencial/i), SEGREDO);

    expect(screen.getByText(/credencial não trafega em texto claro/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /gravar credencial/i })).toBeDisabled();
    expect(salvarIntegracaoProcuracao).not.toHaveBeenCalled();
  });

  it("diz quantos caracteres faltam no segredo curto", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(await screen.findByLabelText(/base url/i), "https://admin.jettax360.com.br");
    await usuario.type(screen.getByLabelText(/credencial/i), "curto");

    expect(screen.getByText(/Faltam 3 caractere/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /gravar credencial/i })).toBeDisabled();
  });

  it("avisa que o Jettax não publica API e aponta a importação por lista", async () => {
    montar();
    expect(await screen.findByText(/não publica API de procurações/i)).toBeInTheDocument();
  });
});
