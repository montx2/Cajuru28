/**
 * `ModalCertificado` unificou os dois modais de upload de A1. O teste trava a
 * regra que divergia entre eles: sem senha o envio não é liberado.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModalCertificado } from "@/components/fiscal/ModalCertificado";
import { ProvedorToast } from "@/components/ui/Toast";

vi.mock("@/lib/api", () => ({
  api: { enviarCertificado: vi.fn().mockResolvedValue({ validade: "2027-01-31T00:00:00Z" }) },
  ApiError: class extends Error {},
}));

function montar(props: Partial<React.ComponentProps<typeof ModalCertificado>> = {}) {
  return render(
    <ProvedorToast>
      <ModalCertificado aberto aoFechar={() => {}} aoInstalar={() => {}} empresaId={7} {...props} />
    </ProvedorToast>
  );
}

const arquivoPfx = () => new File(["conteudo"], "empresa.pfx", { type: "application/x-pkcs12" });

describe("ModalCertificado", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mantém 'Instalar certificado' desabilitado enquanto faltar a senha", async () => {
    const usuario = userEvent.setup();
    montar();

    const instalar = screen.getByRole("button", { name: /instalar certificado/i });
    expect(instalar).toBeDisabled();

    // Só o arquivo não basta — era exatamente aqui que a tela da empresa
    // liberava o envio e deixava o erro estourar depois do upload.
    const entradaArquivo = document.querySelector('input[type="file"]') as HTMLInputElement;
    await usuario.upload(entradaArquivo, arquivoPfx());
    expect(instalar).toBeDisabled();

    await usuario.type(screen.getByLabelText(/senha do certificado/i), "Cert@2024#A1x9");
    expect(instalar).toBeEnabled();
  });

  it("envia empresa, senha e arquivo ao backend sem alterar o contrato", async () => {
    const usuario = userEvent.setup();
    const { api } = await import("@/lib/api");
    montar();

    await usuario.upload(document.querySelector('input[type="file"]') as HTMLInputElement, arquivoPfx());
    await usuario.type(screen.getByLabelText(/senha do certificado/i), "Cert@2024#A1x9");
    await usuario.click(screen.getByRole("button", { name: /instalar certificado/i }));

    expect(api.enviarCertificado).toHaveBeenCalledWith(7, "Cert@2024#A1x9", expect.any(File));
  });

  it("na visão da lista, exige escolher a empresa antes de liberar o envio", async () => {
    const usuario = userEvent.setup();
    montar({ empresaId: null, empresas: [{ valor: "3", rotulo: "Padaria Aurora ME", descricao: "12345678000199" }] });

    await usuario.upload(document.querySelector('input[type="file"]') as HTMLInputElement, arquivoPfx());
    await usuario.type(screen.getByLabelText(/senha do certificado/i), "Cert@2024#A1x9");

    // Arquivo e senha preenchidos, mas sem empresa: continua bloqueado.
    expect(screen.getByRole("button", { name: /instalar certificado/i })).toBeDisabled();
  });
});
