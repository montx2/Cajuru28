/**
 * Importação de certificados em massa: a pasta do computador + a planilha de
 * senhas que o escritório já tem.
 *
 * O contrato travado aqui: a senha global é reserva — quando a planilha traz
 * as senhas (cnpj;senha), o lote sai sem digitar nada; e se não houver senha nem
 * planilha, o lote sai para dedução automática por padrões heurísticos.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModalImportacaoLote } from "@/app/dashboard/empresas/Empresas";
import { ProvedorToast } from "@/components/ui/Toast";
import { certificadosDaPasta } from "@/lib/pastaCertificados";

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

    const planilha = screen.getByLabelText(/planilhas? de senhas/i);
    await usuario.upload(planilha, new File(["cnpj;senha\n12345678000195;abc"], "senhas.csv", { type: "text/csv" }));

    await usuario.selectOptions(screen.getByLabelText(/uf padrão/i), "MG");

    // Sem senha digitada — a planilha cobre o lote.
    expect(screen.getByRole("button", { name: /importar lote/i })).toBeEnabled();
    await usuario.click(screen.getByRole("button", { name: /importar lote/i }));

    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
    const [arquivos, planilhas, senha, uf] = importarEmpresasEmMassa.mock.calls[0];
    expect(arquivos).toHaveLength(2);
    expect((planilhas as File[]).map((arquivo) => arquivo.name)).toEqual(["senhas.csv"]);
    expect(senha).toBe("");
    expect(uf).toBe("MG");
  });

  it("aceita a planilha atual e a antiga no mesmo lote", async () => {
    const usuario = userEvent.setup();
    montar();

    const campoCertificados = await screen.findByLabelText(/ou arquivos individuais/i);
    await usuario.upload(campoCertificados, PFX("12345678000195.pfx"));

    const planilha = screen.getByLabelText(/planilhas de senhas/i);
    await usuario.upload(planilha, [
      new File(["cnpj;senha\n12345678000195;atual"], "atual.csv", { type: "text/csv" }),
      new File(["cnpj;senha\n12345678000195;antiga"], "antiga.csv", { type: "text/csv" }),
    ]);

    await usuario.selectOptions(screen.getByLabelText(/uf padrão/i), "MG");
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
    await usuario.selectOptions(screen.getByLabelText(/uf padrão/i), "MG");

    const botao = screen.getByRole("button", { name: /importar lote/i });
    expect(botao).toBeEnabled();
    await usuario.click(botao);

    await waitFor(() => expect(importarEmpresasEmMassa).toHaveBeenCalledTimes(1));
    const [arquivos, planilhas, senha, uf] = importarEmpresasEmMassa.mock.calls[0];
    expect(arquivos).toHaveLength(1);
    expect(planilhas).toHaveLength(0);
    expect(senha).toBe("");
    expect(uf).toBe("MG");
  });

  it("sem certificados selecionados, o botão fica desabilitado explicando o que falta", async () => {
    montar();
    const botao = screen.getByRole("button", { name: /importar lote/i });
    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute("title", "Escolha a pasta (ou os arquivos) dos certificados");
  });
});
