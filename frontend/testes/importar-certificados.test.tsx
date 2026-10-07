/**
 * Importação de certificados em massa: a pasta do computador e, apenas quando
 * necessário, uma planilha de apoio que o escritório já mantém.
 *
 * A tela não pede senha global nem UF padrão: as senhas podem vir da planilha
 * e a UF é descoberta pelo CNPJ. Sem planilha, o lote segue para identificação
 * automática por padrões heurísticos.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModalImportacaoLote } from "@/app/dashboard/empresas/Empresas";
import { ProvedorToast } from "@/components/ui/Toast";
import { certificadosDaPasta, LIMITE_CERTIFICADOS_POR_LOTE } from "@/lib/pastaCertificados";

const importarEmpresasEmMassa = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    importarEmpresasEmMassa: (...args: unknown[]) => importarEmpresasEmMassa(...args),
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

function montar() {
  return render(
    <ProvedorToast>
      <ModalImportacaoLote aberto aoFechar={() => {}} aoImportar={() => {}} />
    </ProvedorToast>
  );
}

const AGORA = Date.now();
const ONTEM = AGORA - 24 * 60 * 60 * 1000;

const PFX = (nome: string, modificado = AGORA) =>
  new File([new Uint8Array([1, 2, 3, 4])], nome, {
    type: "application/octet-stream",
    lastModified: modificado,
  });

describe("seleção da pasta de certificados", () => {
  it("aceita até 600 certificados no mesmo lote", () => {
    expect(LIMITE_CERTIFICADOS_POR_LOTE).toBe(600);
  });

  it("lê só os .pfx/.p12 e conta o resto como ignorado", () => {
    const tudo = [
      PFX("12345678000195.pfx"),
      PFX("98765432000110.p12"),
      PFX("nota.pdf"),
      PFX("senhas.xlsx"),
      PFX("atalho.lnk"),
    ];
    const { certificados, ignorados } = certificadosDaPasta(tudo);
    expect(certificados.map((arquivo) => arquivo.name)).toEqual(["12345678000195.pfx", "98765432000110.p12"]);
    expect(ignorados).toBe(3);
  });

  it("pasta vazia de certificados não promete nada", () => {
    const { certificados, ignorados } = certificadosDaPasta([PFX("leia-me.txt")]);
    expect(certificados).toEqual([]);
    expect(ignorados).toBe(1);
  });

  it("com o antigo e o atualizado da mesma empresa, só o atualizado segue", () => {
    const antigo = PFX("12345678000195-antigo.pfx", ONTEM);
    const atualizado = PFX("12345678000195-atualizado.pfx", AGORA);
    const { certificados, substituidos, substituicoes } = certificadosDaPasta([antigo, atualizado]);

    expect(certificados.map((arquivo) => arquivo.name)).toEqual(["12345678000195-atualizado.pfx"]);
    expect(substituidos).toBe(1);
    expect(substituicoes[0].cnpj).toBe("12345678000195");
    expect(substituicoes[0].descartados.map((arquivo) => arquivo.name)).toEqual([
      "12345678000195-antigo.pfx",
    ]);
  });

  it("data declarada no nome vale mais que a data de modificação", () => {
    // O antigo foi baixado hoje; o atualizado foi copiado há tempos — mas
    // o nome diz qual versão é qual.
    const recuperadoAgora = PFX("12345678000195_2025.pfx", AGORA);
    const copiadoAntes = PFX("12345678000195_2027.pfx", ONTEM);
    const { certificados, substituidos } = certificadosDaPasta([recuperadoAgora, copiadoAntes]);

    expect(certificados.map((arquivo) => arquivo.name)).toEqual(["12345678000195_2027.pfx"]);
    expect(substituidos).toBe(1);
  });

  it("empresas diferentes não são agrupadas", () => {
    const { certificados, substituidos, substituicoes } = certificadosDaPasta([
      PFX("12345678000195.pfx"),
      PFX("11444777000161.pfx"),
    ]);

    expect(certificados).toHaveLength(2);
    expect(substituidos).toBe(0);
    expect(substituicoes).toEqual([]);
  });
});

describe("lote com planilha de senhas", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    importarEmpresasEmMassa.mockResolvedValue({
      total: 2,
      criadas: 2,
      certificados: 0,
      ja_existiam: 0,
      erros: 0,
      itens: [],
    });
  });

  it("envia o lote sem senha global quando a planilha traz as senhas", async () => {
    const usuario = userEvent.setup();
    montar();

    const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
    await usuario.upload(campoCertificados, [PFX("12345678000195.pfx"), PFX("98765432000110.pfx")]);

    const planilha = screen.getByLabelText(/planilha de apoio/i);
    await usuario.upload(planilha, new File(["cnpj;senha\n12345678000195;abc"], "senhas.csv", { type: "text/csv" }));

    expect(screen.getByRole("button", { name: /importar lote/i })).toBeEnabled();
    await usuario.click(screen.getByRole("button", { name: /importar lote/i }));

    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
    const [arquivos, planilhas] = importarEmpresasEmMassa.mock.calls[0];
    expect(arquivos).toHaveLength(2);
    expect((planilhas as File[]).map((arquivo) => arquivo.name)).toEqual(["senhas.csv"]);
  });

  it("aceita a planilha atual e a antiga no mesmo lote", async () => {
    const usuario = userEvent.setup();
    montar();

    const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
    await usuario.upload(campoCertificados, PFX("12345678000195.pfx"));

    const planilha = screen.getByLabelText(/planilha de apoio/i);
    await usuario.upload(planilha, [
      new File(["cnpj;senha\n12345678000195;atual"], "atual.csv", { type: "text/csv" }),
      new File(["cnpj;senha\n12345678000195;antiga"], "antiga.csv", { type: "text/csv" }),
    ]);

    await usuario.click(screen.getByRole("button", { name: /importar lote/i }));

    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
    const [, planilhas] = importarEmpresasEmMassa.mock.calls[0];
    expect((planilhas as File[]).map((arquivo) => arquivo.name)).toEqual(["atual.csv", "antiga.csv"]);
  });

  it("permite importar lote sem planilha e sem senha global, identificando senhas automaticamente", async () => {
    const usuario = userEvent.setup();
    montar();

    const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
    await usuario.upload(campoCertificados, PFX("12345678000195.pfx"));

    const botao = screen.getByRole("button", { name: /importar lote/i });
    expect(botao).toBeEnabled();
    await usuario.click(botao);

    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
    const [arquivos, planilhas] = importarEmpresasEmMassa.mock.calls[0];
    expect(arquivos).toHaveLength(1);
    expect(planilhas).toHaveLength(0);
  });

  it("não pede senha global nem UF: esses dados são encontrados automaticamente", () => {
    montar();

    expect(screen.queryByLabelText(/senha dos certificados/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/uf padrão/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/planilha de apoio/i)).toBeInTheDocument();
  });

  it("sem certificados selecionados, o botão fica desabilitado explicando o que falta", async () => {
    montar();
    const botao = screen.getByRole("button", { name: /importar lote/i });
    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute("title", "Escolha a pasta (ou os arquivos) dos certificados");
  });
});

describe("retorno da planilha de apoio no resultado do lote", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function importarComPlanilha(usuario: ReturnType<typeof userEvent.setup>) {
    const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
    await usuario.upload(campoCertificados, PFX("21260898000107.pfx"));
    const planilha = screen.getByLabelText(/planilha de apoio/i);
    await usuario.upload(
      planilha,
      new File(["21260898000107.pfx;21.260.898/0001-07;ICP-Brasil;7cs19Pfi;09/03/2027"], "certificados_e_senhas.csv", {
        type: "text/csv",
      })
    );
    await usuario.click(screen.getByRole("button", { name: /importar lote/i }));
    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
  }

  it("diz quantas linhas e senhas a planilha rendeu", async () => {
    importarEmpresasEmMassa.mockResolvedValue({
      total: 1,
      criadas: 1,
      certificados: 0,
      ja_existiam: 0,
      erros: 0,
      itens: [],
      linhas_da_planilha: 52,
      senhas_da_planilha: 50,
    });
    const usuario = userEvent.setup();
    montar();

    await importarComPlanilha(usuario);

    expect(await screen.findByText(/52 linhas lidas/i)).toBeInTheDocument();
    expect(screen.getByText(/50 com senha/i)).toBeInTheDocument();
  });

  it("avisa quando a planilha anexada não rendeu nenhuma linha", async () => {
    importarEmpresasEmMassa.mockResolvedValue({
      total: 1,
      criadas: 0,
      certificados: 0,
      ja_existiam: 0,
      erros: 1,
      itens: [],
      linhas_da_planilha: 0,
      senhas_da_planilha: 0,
    });
    const usuario = userEvent.setup();
    montar();

    await importarComPlanilha(usuario);

    expect(await screen.findByText(/planilha anexada não rendeu nenhuma linha/i)).toBeInTheDocument();
  });

  it("sem planilha anexada, não fala de planilha", async () => {
    importarEmpresasEmMassa.mockResolvedValue({
      total: 1,
      criadas: 1,
      certificados: 0,
      ja_existiam: 0,
      erros: 0,
      itens: [],
      linhas_da_planilha: 0,
      senhas_da_planilha: 0,
    });
    const usuario = userEvent.setup();
    montar();

    const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
    await usuario.upload(campoCertificados, PFX("21260898000107.pfx"));
    await usuario.click(screen.getByRole("button", { name: /importar lote/i }));
    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));

    expect(await screen.findByText("Processados")).toBeInTheDocument();
    expect(screen.queryByText(/linhas lidas/i)).not.toBeInTheDocument();
  });
});
