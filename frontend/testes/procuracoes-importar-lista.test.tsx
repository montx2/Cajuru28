/**
 * Importação da lista de procurações colada da tela do fornecedor.
 *
 * O caminho (a) do módulo: como o Jettax 360 não publica API para a tela
 * `prevention/ecac/procurations`, o operador traz a lista. O que este teste
 * trava é o contrato da tela com a API — origem declarada (que define a
 * precedência entre fontes), aba declarada e a exibição das pendências, que é
 * o que transforma "ignorou 3 linhas" em tarefa.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportarLista } from "@/app/dashboard/procuracoes/ImportarLista";
import { ProvedorToast } from "@/components/ui/Toast";

const importarListaProcuracoes = vi.fn();
const importarPlanilhaProcuracoes = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    importarListaProcuracoes: (...args: unknown[]) => importarListaProcuracoes(...args),
    importarPlanilhaProcuracoes: (...args: unknown[]) => importarPlanilhaProcuracoes(...args),
  },
  ApiError: class extends Error {
    status = 0;
    problemas: unknown[] = [];
  },
}));

vi.mock("@/components/shell/ProvedorSessao", () => ({
  useSessao: () => ({ somenteLeitura: false, papel: "admin", ehAdmin: true }),
}));

const COLAGEM = "CLIENTE UM LTDA\n12.345.678/0001-95\nSim\n01/02/2024\n31/12/2030\nVálida";

const RESULTADO = {
  fonte: "jettax360",
  recebidos: 2,
  criados: 1,
  atualizados: 0,
  inalterados: 0,
  ignorados: 1,
  invalidos: 0,
  mensagem: "2 recebido(s): 1 criado(s), 0 atualizado(s), 0 sem mudança, 1 ignorado(s), 0 inválido(s).",
  erros: [
    {
      documento: "04252011000110",
      nome: "EMPRESA DE FORA SA",
      codigo: "EMPRESA_NAO_CADASTRADA",
      mensagem: "Documento fora da carteira. Cadastre a empresa em Empresas (com UF) e rode a importação de novo.",
    },
  ],
};

function montar(aoImportar = vi.fn()) {
  return render(
    <ProvedorToast>
      <ImportarLista aberta aoFechar={() => {}} aoImportar={aoImportar} />
    </ProvedorToast>
  );
}

describe("importar lista colada", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    importarListaProcuracoes.mockResolvedValue(RESULTADO);
  });

  it("não deixa importar com a caixa vazia", () => {
    montar();
    expect(screen.getByRole("button", { name: /^importar lista$/i })).toBeDisabled();
  });

  it("manda o texto com a origem declarada — é ela que define a precedência", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));

    await waitFor(() => expect(importarListaProcuracoes).toHaveBeenCalledTimes(1));
    expect(importarListaProcuracoes).toHaveBeenCalledWith({
      texto: COLAGEM,
      fonte: "jettax360",
      situacao_padrao: "",
    });
  });

  it("declara a aba de origem quando o operador a escolhe", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.selectOptions(screen.getByLabelText(/situação da aba/i), "expirada");
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));

    await waitFor(() =>
      expect(importarListaProcuracoes).toHaveBeenCalledWith(
        expect.objectContaining({ situacao_padrao: "expirada" })
      )
    );
  });

  it("lista as pendências com nome e documento, sem criar empresa por conta própria", async () => {
    const usuario = userEvent.setup();
    const aoImportar = vi.fn();
    montar(aoImportar);

    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));

    await screen.findByText(/documento fora da carteira/i);
    expect(screen.getByText("04252011000110")).toBeInTheDocument();
    expect(screen.getByText(/EMPRESA DE FORA SA/)).toBeInTheDocument();
    expect(aoImportar).toHaveBeenCalled();
  });

  it("envia o arquivo exportado com a mesma origem declarada", async () => {
    const usuario = userEvent.setup();
    importarPlanilhaProcuracoes.mockResolvedValue({ ...RESULTADO, erros: [] });
    montar();

    const arquivo = new File(["cnpj;razao_social\n"], "procuracoes.csv", { type: "text/csv" });
    await usuario.upload(document.querySelector('input[type="file"]') as HTMLInputElement, arquivo);

    await waitFor(() => expect(importarPlanilhaProcuracoes).toHaveBeenCalledTimes(1));
    expect(importarPlanilhaProcuracoes).toHaveBeenCalledWith(arquivo, {
      fonte: "jettax360",
      situacaoPadrao: "",
    });
  });
});
