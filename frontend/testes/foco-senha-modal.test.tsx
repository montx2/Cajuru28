/**
 * Regressão do bug crítico: o campo de senha do certificado A1 perdia o foco
 * para o botão "Fechar" (X) a cada caractere digitado.
 *
 * O teste reproduz o padrão real de uso — `aoFechar={() => setAberto(false)}`
 * escrito inline no JSX, ou seja, uma função com identidade nova a cada render
 * — e digita uma senha de 14 caracteres com maiúsculas, minúsculas, números e
 * símbolos SEM reclicar no campo. Se o focus trap reexecutar, o foco vai para o
 * X e o input termina com uma fração da senha.
 */
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "@/components/ui/Modal";
import { Entrada } from "@/components/ui/Campo";

const SENHA = "Cert@2024#A1x9"; // 14 caracteres: maiúsculas, minúsculas, números e símbolos

function TelaCertificado() {
  const [aberto, setAberto] = useState(true);
  const [senha, setSenha] = useState("");
  return (
    <Modal
      aberto={aberto}
      // Identidade nova a cada render — exatamente como as telas escrevem.
      aoFechar={() => setAberto(false)}
      titulo="Enviar certificado A1"
      rodape={<button type="button">Instalar certificado</button>}
    >
      <Entrada
        rotulo="Senha do certificado"
        type="password"
        autoComplete="off"
        value={senha}
        onChange={(evento) => setSenha(evento.target.value)}
      />
    </Modal>
  );
}

describe("campo de senha dentro do modal", () => {
  it("mantém o foco no input durante a digitação inteira da senha", async () => {
    const usuario = userEvent.setup();
    render(<TelaCertificado />);

    const campo = screen.getByLabelText(/senha do certificado/i);
    await usuario.click(campo);

    for (const caractere of SENHA) {
      await usuario.keyboard(caractere === "{" ? "{{" : caractere);
      // A cada tecla: o foco continua no input, nunca no botão Fechar.
      expect(document.activeElement).toBe(campo);
    }

    expect(campo).toHaveValue(SENHA);
    expect(screen.getByLabelText("Fechar")).not.toBe(document.activeElement);
  });

  it("leva o foco para dentro do diálogo ao abrir", async () => {
    render(<TelaCertificado />);
    // jsdom não calcula layout, então o foco inicial cai no container do
    // diálogo em vez do primeiro focável — o que importa aqui é que o foco
    // entrou na camada e não ficou na página de trás.
    await waitFor(() => expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true));
  });
});
