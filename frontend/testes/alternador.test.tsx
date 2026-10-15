/**
 * O interruptor é o controle que mais aparenta estado — se ele mente, o
 * operador desliga o que está ligado (ou o contrário). Dois defeitos reais
 * viraram teste: o botão saía da calha quando ligado e o desenho desligado
 * parecia ligado. O terceiro é de alinhamento: na grade de filtros ele ficava
 * na altura do rótulo dos campos vizinhos.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Alternador } from "@/components/ui/Campo";

describe("Alternador", () => {
  it("nasce desligado, com o nome acessível do rótulo visível", () => {
    render(<Alternador rotulo="Sincronismo automático" descricao="Ligado, captura sozinho." ligado={false} aoMudar={() => undefined} />);

    const chave = screen.getByRole("switch", { name: /sincronismo automático/i });
    expect(chave).toHaveAttribute("aria-checked", "false");
    expect(chave).toBeEnabled();
    // A descrição é o apoio do controle, não texto solto.
    expect(chave).toHaveAccessibleDescription(/captura sozinho/i);
  });

  it("desligado e ligado são desenhos diferentes — e o botão não escapa da calha", async () => {
    const usuario = userEvent.setup();
    const aoMudar = vi.fn();
    const { rerender } = render(<Alternador rotulo="Acesso ativo" ligado={false} aoMudar={aoMudar} />);

    const chave = screen.getByRole("switch", { name: "Acesso ativo" });
    const botao = chave.querySelector("span[aria-hidden='true']");
    expect(botao).not.toBeNull();
    // Desligado: calha neutra, botão à esquerda.
    expect(chave.className).toContain("bg-fundo-afundado");
    expect(chave.className).not.toContain("bg-acento ");
    expect(botao?.className).toContain("translate-x-0");

    await usuario.click(chave);
    expect(aoMudar).toHaveBeenCalledWith(true);

    rerender(<Alternador rotulo="Acesso ativo" ligado aoMudar={aoMudar} />);
    expect(screen.getByRole("switch", { name: "Acesso ativo" })).toHaveAttribute("aria-checked", "true");
    const botaoLigado = screen.getByRole("switch", { name: "Acesso ativo" }).querySelector("span[aria-hidden='true']");
    // Ligado: calha cheia na cor de ação, botão à direita dentro da calha
    // (20 px de deslocamento + 3 px de folga + 16 px de botão = 39 dos 44 px).
    expect(screen.getByRole("switch", { name: "Acesso ativo" }).className).toContain("bg-acento");
    expect(botaoLigado?.className).toContain("translate-x-5");
    expect(botaoLigado?.className).not.toMatch(/translate-x-(6|7|8|9|10|11|12)/);
  });

  it("fica no mesmo ritmo de um campo: rótulo de 18 px e faixa de controle de 40 px", () => {
    const { container } = render(<Alternador rotulo="Empresa ativa" ligado aoMudar={() => undefined} />);

    const rotulo = container.querySelector("span[id$='-rotulo']");
    expect(rotulo?.className).toContain("text-xs");
    expect(rotulo?.parentElement?.className).toContain("min-h-[18px]");
    const faixa = container.querySelector("span[id$='-rotulo']")?.parentElement?.nextElementSibling;
    expect(faixa?.className).toContain("min-h-[40px]");
    expect(faixa?.className).toContain("items-center");
  });

  it("desabilitado explica o motivo e não muda de valor", async () => {
    const aoMudar = vi.fn();
    render(<Alternador rotulo="Forçar" descricao="Só admin." ligado={false} aoMudar={aoMudar} desabilitado motivoDesabilitado="Seu papel é leitura." />);

    const chave = screen.getByRole("switch", { name: "Forçar" });
    expect(chave).toBeDisabled();
    expect(chave).toHaveAccessibleDescription(/papel é leitura/i);
    await userEvent.setup().click(chave).catch(() => undefined);
    expect(aoMudar).not.toHaveBeenCalled();
  });
});
