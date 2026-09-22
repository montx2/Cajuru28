/**
 * `CampoSenha` é usado no login, no certificado A1 e no cadastro de usuário.
 * Estes testes fixam o contrato dos três: alternar visibilidade não pode
 * derrubar o foco nem perder o que já foi digitado.
 */
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CampoSenha } from "@/components/ui/CampoSenha";

function Campo() {
  const [valor, setValor] = useState("");
  return <CampoSenha rotulo="Senha do certificado" value={valor} onChange={(e) => setValor(e.target.value)} />;
}

describe("CampoSenha", () => {
  it("começa oculto e alterna para texto visível sem perder o valor", async () => {
    const usuario = userEvent.setup();
    render(<Campo />);
    const campo = screen.getByLabelText(/senha do certificado/i);

    await usuario.type(campo, "Cert@2024#A1x9");
    expect(campo).toHaveAttribute("type", "password");

    await usuario.click(screen.getByRole("button", { name: /mostrar senha/i }));
    expect(campo).toHaveAttribute("type", "text");
    expect(campo).toHaveValue("Cert@2024#A1x9");

    await usuario.click(screen.getByRole("button", { name: /ocultar senha/i }));
    expect(campo).toHaveAttribute("type", "password");
    expect(campo).toHaveValue("Cert@2024#A1x9");
  });

  it("mantém a digitação fluindo depois de alternar a visibilidade", async () => {
    const usuario = userEvent.setup();
    render(<Campo />);
    const campo = screen.getByLabelText(/senha do certificado/i);

    await usuario.type(campo, "Abc");
    await usuario.click(screen.getByRole("button", { name: /mostrar senha/i }));
    await usuario.click(campo);
    await usuario.type(campo, "123!");

    expect(campo).toHaveValue("Abc123!");
    expect(document.activeElement).toBe(campo);
  });

  it("fica fora da ordem de tabulação, para o Tab ir da senha à ação", async () => {
    render(<Campo />);
    expect(screen.getByRole("button", { name: /mostrar senha/i })).toHaveAttribute("tabindex", "-1");
  });
});
