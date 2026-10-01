/**
 * Importação da lista de procurações colada da tela do fornecedor.
 *
 * A planilha do escritório é o caminho padrão; fontes externas ficam como
 * segunda opção e mostram instrução somente quando escolhidas. O teste trava o
 * contrato da tela com a API — origem declarada, aba e pendências acionáveis.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportarLista } from "@/app/dashboard/procuracoes/ImportarLista";
import { ProvedorToast } from "@/components/ui/Toast";

const importarListaProcuracoes = vi.fn();
const importarPlanilhaProcuracoes = vi.fn();
const cadastrarEmpresasPendencias = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    importarListaProcuracoes: (...args: unknown[]) => importarListaProcuracoes(...args),
    importarPlanilhaProcuracoes: (...args: unknown[]) => importarPlanilhaProcuracoes(...args),
    cadastrarEmpresasPendencias: (...args: unknown[]) => cadastrarEmpresasPendencias(...args),
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

  it("começa pela planilha e só mostra a ajuda externa quando essa fonte é escolhida", async () => {
    const usuario = userEvent.setup();
    montar();

    const origem = screen.getByLabelText(/origem do dado/i) as HTMLSelectElement;
    expect(origem.value).toBe("planilha");
    expect(screen.queryByText(/como preparar a lista exportada/i)).not.toBeInTheDocument();

    await usuario.selectOptions(origem, "jettax360");

    expect(screen.getByText(/como preparar a lista exportada/i)).toBeInTheDocument();
  });

  it("manda o texto com a origem declarada — é ela que define a precedência", async () => {
    const usuario = userEvent.setup();
    montar();

    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));

    await waitFor(() => expect(importarListaProcuracoes).toHaveBeenCalledTimes(1));
    expect(importarListaProcuracoes).toHaveBeenCalledWith({
      texto: COLAGEM,
      fonte: "planilha",
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

  it("oferece as quatro abas do painel — inclusive 'Sem procuração'", async () => {
    const usuario = userEvent.setup();
    montar();

    const selecao = screen.getByLabelText(/situação da aba/i) as HTMLSelectElement;
    const valores = Array.from(selecao.options).map((opcao) => opcao.value);
    expect(valores).toEqual(["", "expirada", "ativa", "sem_procuracao"]);
    expect(screen.getByText(/aba “sem procuração”/i)).toBeInTheDocument();

    // A aba “Sem procuração” é uma afirmação do painel: quem aparece lá não
    // autorizou — a importação não pode chamar isso de “situação indeterminada”.
    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.selectOptions(selecao, "sem_procuracao");
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));

    await waitFor(() =>
      expect(importarListaProcuracoes).toHaveBeenCalledWith(
        expect.objectContaining({ situacao_padrao: "sem_procuracao" })
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


  it("cadastra as pendências marcadas e importa a mesma lista de novo", async () => {
    const usuario = userEvent.setup();
    importarListaProcuracoes.mockResolvedValue(RESULTADO);
    cadastrarEmpresasPendencias.mockResolvedValue({
      total: 1,
      criadas: 1,
      certificados: 0,
      ja_existiam: 0,
      erros: 0,
      itens: [],
    });
    montar();

    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));

    // A pendência aparece com marcação — o caminho de um clique é o padrão.
    const caixa = await screen.findByLabelText(/04252011000110/i);
    expect(caixa).toBeChecked();

    await usuario.click(screen.getByRole("button", { name: /cadastrar 1 empresa e importar de novo/i }));

    // O que sai da tela é o que a lista trouxe: documento + nome.
    await waitFor(() =>
      expect(cadastrarEmpresasPendencias).toHaveBeenCalledWith([
        { documento: "04252011000110", razao_social: "EMPRESA DE FORA SA" },
      ])
    );
    // E a mesma colagem é importada de novo — sem novo copia-e-cola.
    await waitFor(() => expect(importarListaProcuracoes).toHaveBeenCalledTimes(2));
    expect(importarListaProcuracoes).toHaveBeenLastCalledWith({
      texto: COLAGEM,
      fonte: "planilha",
      situacao_padrao: "",
    });
  });

  it("desmarcar uma pendência tira ela do cadastro em lote", async () => {
    const usuario = userEvent.setup();
    importarListaProcuracoes.mockResolvedValue(RESULTADO);
    montar();

    await usuario.type(screen.getByLabelText(/lista copiada da tela/i), COLAGEM);
    await usuario.click(screen.getByRole("button", { name: /^importar lista$/i }));
    await screen.findByLabelText(/04252011000110/i);

    await usuario.click(screen.getByLabelText(/04252011000110/i));
    // Sem seleção não há o que cadastrar: o botão não promete.
    expect(screen.getByRole("button", { name: /cadastrar 0 empresas e importar de novo/i })).toBeDisabled();
    expect(cadastrarEmpresasPendencias).not.toHaveBeenCalled();
  });

  it("envia o arquivo exportado com a mesma origem declarada", async () => {
    const usuario = userEvent.setup();
    importarPlanilhaProcuracoes.mockResolvedValue({ ...RESULTADO, erros: [] });
    montar();

    const arquivo = new File(["cnpj;razao_social\n"], "procuracoes.csv", { type: "text/csv" });
    await usuario.upload(document.querySelector('input[type="file"]') as HTMLInputElement, arquivo);

    await waitFor(() => expect(importarPlanilhaProcuracoes).toHaveBeenCalledTimes(1));
    expect(importarPlanilhaProcuracoes).toHaveBeenCalledWith(arquivo, {
      fonte: "planilha",
      situacaoPadrao: "",
    });
  });
});
