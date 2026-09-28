/**
 * Importação manual de XMLs (ZIP/arquivos soltos) — o caminho que não gasta
 * cota da SEFAZ, para quando outro sistema fica com a consulta automática.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportarXmls } from "@/app/dashboard/importacoes/ImportarXmls";
import { ProvedorToast } from "@/components/ui/Toast";
import type { ImportacaoXmlResposta } from "@/lib/types";

const importarXmls = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    importarXmls: (...args: unknown[]) => importarXmls(...args),
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
      <ImportarXmls />
    </ProvedorToast>
  );
}

const RESPOSTA: ImportacaoXmlResposta = {
  total: 3,
  importados: 2,
  duplicadas: 1,
  sem_empresa: 0,
  nao_reconhecidos: 0,
  erros: 0,
  itens: [
    {
      origem: "nfe_123.xml",
      tipo: "nfe",
      chave: "3526089999999900018855001",
      razao_social: "EMPRESA CLIENTE LTDA",
      cnpj_cpf: "12345678000199",
      status: "importado",
      mensagem: "Nota gravada no acervo.",
    },
    {
      origem: "cte_789.xml",
      tipo: "cte",
      chave: "3526089999999900018857003",
      razao_social: "EMPRESA CLIENTE LTDA",
      cnpj_cpf: "12345678000199",
      status: "importado",
      mensagem: "Nota gravada no acervo.",
    },
    {
      origem: "nfe_123.xml",
      tipo: "nfe",
      chave: "3526089999999900018855001",
      razao_social: "EMPRESA CLIENTE LTDA",
      cnpj_cpf: "12345678000199",
      status: "duplicada",
      mensagem: "Já estava no acervo; a fonte ficou registrada.",
    },
  ],
};

describe("importar XMLs do computador", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    importarXmls.mockResolvedValue(RESPOSTA);
  });

  it("envia ZIP e XMLs soltos e mostra o resultado por arquivo", async () => {
    const usuario = userEvent.setup();
    montar();

    const campo = await screen.findByLabelText(/zip ou xmls exportados/i);
    const zip = new File([new Uint8Array([1, 2])], "exportacao.zip", { type: "application/zip" });
    const xml = new File(["<nfeProc/>"], "nfe_123.xml", { type: "application/xml" });
    await usuario.upload(campo, [zip, xml]);

    await usuario.click(screen.getByRole("button", { name: /importar xmls/i }));

    await waitFor(() => expect(importarXmls).toHaveBeenCalledTimes(1));
    expect((importarXmls.mock.calls[0][0] as File[]).map((arquivo) => arquivo.name)).toEqual([
      "exportacao.zip",
      "nfe_123.xml",
    ]);

    expect(await screen.findByText("Importadas")).toBeInTheDocument();
    expect(screen.getByText("Já existiam")).toBeInTheDocument();
    expect(screen.getAllByText("EMPRESA CLIENTE LTDA")).toHaveLength(3);
    expect(screen.getByText("Já existia")).toBeInTheDocument();
  });

  it("sem arquivo, o botão diz o que falta e nada é enviado", async () => {
    montar();

    const botao = screen.getByRole("button", { name: /importar xmls/i });
    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute("title", "Escolha um .zip ou arquivos .xml");
    expect(importarXmls).not.toHaveBeenCalled();
  });
});
