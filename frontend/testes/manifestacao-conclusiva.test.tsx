/**
 * Manifestação conclusiva: o caminho da nota que passou dos 10 dias.
 *
 * O robô registra a Ciência da Operação sozinho, mas a SEFAZ só a aceita até 10
 * dias da autorização — depois disso (cStat 596) o XML completo só sai com um
 * evento conclusivo, que diz o que aconteceu com a operação. É ato de negócio:
 * a tela precisa explicar o efeito de cada escolha e não pode mandar à SEFAZ um
 * evento que já sabe que será recusado.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManifestacaoConclusiva } from "@/components/fiscal/ManifestacaoConclusiva";
import { ProvedorToast } from "@/components/ui/Toast";
import type { DocumentoDetalhe } from "@/lib/types";

const manifestarConclusiva = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    manifestarConclusiva: (...args: unknown[]) => manifestarConclusiva(...args),
  },
}));

const documento = {
  id: 7,
  chave_acesso: "31260907485646000155550010000602201187626989",
  manifestacao_cstat: "596",
  leiaute: "resumo",
} as unknown as DocumentoDetalhe;

function abrir() {
  const aoConcluir = vi.fn();
  render(
    <ProvedorToast>
      <ManifestacaoConclusiva documento={documento} aoConcluir={aoConcluir} />
    </ProvedorToast>
  );
  return aoConcluir;
}

describe("manifestação conclusiva da NF-e", () => {
  beforeEach(() => {
    manifestarConclusiva.mockReset();
  });

  it("explica por que a Ciência não serve mais e mostra as três escolhas", async () => {
    const usuario = userEvent.setup();
    abrir();

    await usuario.click(screen.getByRole("button", { name: /manifestar operação/i }));

    expect(screen.getByText(/passou dos 10 dias da autorização/i)).toBeTruthy();
    expect(screen.getByRole("radio", { name: /confirmação da operação/i })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /desconhecimento da operação/i })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /operação não realizada/i })).toBeTruthy();
  });

  it("avisa que o Desconhecimento não devolve o XML completo", async () => {
    const usuario = userEvent.setup();
    abrir();

    await usuario.click(screen.getByRole("button", { name: /manifestar operação/i }));
    await usuario.click(screen.getByRole("radio", { name: /desconhecimento da operação/i }));

    expect(screen.getByText(/NÃO devolve o XML completo/i)).toBeTruthy();
  });

  it("não envia evento sem justificativa válida", async () => {
    const usuario = userEvent.setup();
    abrir();

    await usuario.click(screen.getByRole("button", { name: /manifestar operação/i }));
    await usuario.click(screen.getByRole("radio", { name: /operação não realizada/i }));
    await usuario.type(screen.getByLabelText(/justificativa/i), "curta");
    await usuario.click(screen.getByRole("button", { name: /registrar na sefaz/i }));

    expect(await screen.findByText(/A SEFAZ exige justificativa de 15 a 255/i)).toBeTruthy();
    expect(manifestarConclusiva).not.toHaveBeenCalled();
  });

  it("manda o tipo, a justificativa e o id da nota", async () => {
    const usuario = userEvent.setup();
    manifestarConclusiva.mockResolvedValue([
      { documento_id: 7, chave_acesso: documento.chave_acesso, ok: true, mensagem: "registrado" },
    ]);
    const aoConcluir = abrir();

    await usuario.click(screen.getByRole("button", { name: /manifestar operação/i }));
    await usuario.click(screen.getByRole("radio", { name: /operação não realizada/i }));
    await usuario.type(
      screen.getByLabelText(/justificativa/i),
      "Mercadoria recusada na entrega e devolvida ao emitente"
    );
    await usuario.click(screen.getByRole("button", { name: /registrar na sefaz/i }));

    await waitFor(() =>
      expect(manifestarConclusiva).toHaveBeenCalledWith(
        [7],
        "nao_realizada",
        "Mercadoria recusada na entrega e devolvida ao emitente"
      )
    );
    await waitFor(() => expect(aoConcluir).toHaveBeenCalled());
  });

  it("mostra o motivo quando a SEFAZ recusa o evento", async () => {
    const usuario = userEvent.setup();
    manifestarConclusiva.mockResolvedValue([
      {
        documento_id: 7,
        chave_acesso: documento.chave_acesso,
        ok: false,
        mensagem: "cStat 573: duplicidade de evento",
      },
    ]);
    abrir();

    await usuario.click(screen.getByRole("button", { name: /manifestar operação/i }));
    await usuario.click(screen.getByRole("button", { name: /registrar na sefaz/i }));

    expect(await screen.findByText(/duplicidade de evento/i)).toBeTruthy();
  });
});
