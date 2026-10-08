/**
 * Guardas do design system (Bloco E, fase 1).
 *
 * A fase 1 começou pelo inventário: 20 ações de texto ("Ver todos", "Limpar",
 * "Fechar", "Consultar CNPJ") escritas à mão em 10 arquivos, cada uma com uma
 * combinação própria de tamanho, cor e padding — o mesmo papel com cinco
 * aparências. O que estes testes travam:
 *
 *  1. ação de texto isolada usa o primitivo (`Botao`/`BotaoLink`), não classes
 *     soltas reescritas a cada tela;
 *  2. link DENTRO de frase usa `.link-prosa` (herda a cor do texto em volta);
 *  3. a variante de link não herda padding de botão — o `px-0` da variante e o
 *     `px-3` do tamanho conviviam no classList e o utilitário vencia, deixando
 *     um "link de texto" com cara de botão sem fundo;
 *  4. o que ficou de fora está contado e nomeado: um par novo escrito à mão
 *     quebra o teste em vez de virar o sexto jeito de fazer a mesma coisa.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Botao, BotaoLink } from "@/components/ui/Botao";

const RAIZ = resolve(__dirname, "..");

function arquivosTsx(diretorios: string[]): string[] {
  const encontrados: string[] = [];
  for (const diretorio of diretorios) {
    const base = resolve(RAIZ, diretorio);
    const visitar = (caminho: string) => {
      for (const entrada of readdirSync(caminho)) {
        const completo = resolve(caminho, entrada);
        if (statSync(completo).isDirectory()) visitar(completo);
        else if (completo.endsWith(".tsx")) encontrados.push(completo);
      }
    };
    visitar(base);
  }
  return encontrados;
}

/**
 * Ação de texto à mão que ainda existe, com o motivo — e o dono da decisão.
 * Só `components/ui` e os dois "chips" locais (sino, tabela de empresas) e a
 * ação do painel de documento: todos são fase 2 (hierarquia por tela), onde
 * podem virar botão de verdade em vez de link fantasma.
 */
const PENDENTES: Record<string, number> = {
  "components/ui/Botao.tsx": 2, // as duas variantes (link, link-sutil) — a definição
  "components/shell/Header.tsx": 2, // chip do sino + ação local do popover
  "components/fiscal/PainelDocumento.tsx": 1, // ação secundária do painel
  "app/dashboard/empresas/Empresas.tsx": 1, // chip "Consultar CNPJ" (tem estado desabilitado)
};

describe("ação de texto tem um lugar só", () => {
  it("nenhuma tela nova reescreve o visual do botão-link à mão", () => {
    const infratores: string[] = [];
    for (const arquivo of arquivosTsx(["app", "components"])) {
      const relativo = arquivo.slice(RAIZ.length + 1).replace(/\\/g, "/");
      const ocorrencias = (readFileSync(arquivo, "utf8").match(/underline-offset-4 hover:underline/g) ?? []).length;
      const permitido = PENDENTES[relativo] ?? 0;
      if (ocorrencias > permitido) {
        infratores.push(`${relativo}: ${ocorrencias} (permitido ${permitido})`);
      }
    }
    expect(
      infratores,
      "Use `Botao variante=\"link\"` / `link-sutil` para ação isolada, ou `className=\"link-prosa\"` para link dentro de frase.",
    ).toEqual([]);
  });

  it("o que ficou pendente está contado — a lista não pode crescer em silêncio", () => {
    for (const [arquivo, esperado] of Object.entries(PENDENTES)) {
      const ocorrencias = (readFileSync(resolve(RAIZ, arquivo), "utf8").match(/underline-offset-4 hover:underline/g) ?? []).length;
      expect(ocorrencias, `${arquivo} (fase 2)`).toBe(esperado);
    }
  });

  it("link em prosa é uma classe só, declarada no CSS", () => {
    const css = readFileSync(resolve(RAIZ, "app/globals.css"), "utf8");
    expect(css).toContain(".link-prosa");
    const usos = arquivosTsx(["app", "components"]).filter((arquivo) =>
      readFileSync(arquivo, "utf8").includes('className="link-prosa'),
    );
    expect(usos.length).toBeGreaterThan(0);
  });
});

describe("variante de link não carrega geometria de botão", () => {
  it("tamanho do link muda só o texto — sem padding de botão", () => {
    for (const tamanho of ["sm", "md", "lg"] as const) {
      const { unmount } = render(
        <Botao variante="link" tamanho={tamanho}>
          Ver todos
        </Botao>,
      );
      const botao = screen.getByRole("button", { name: "Ver todos" });
      expect(botao.className, `link ${tamanho}`).toContain("px-0");
      expect(botao.className, `link ${tamanho} não pode ter padding de botão`).not.toMatch(/\bpx-[1-9]/);
      unmount();
    }
  });

  it("ação de texto neutra não usa o acento", () => {
    render(
      <Botao variante="link-sutil" tamanho="sm">
        Fechar
      </Botao>,
    );
    const botao = screen.getByRole("button", { name: "Fechar" });
    expect(botao.className).toContain("text-tinta-suave");
    expect(botao.className).not.toContain("text-acento");
  });

  it("BotaoLink de ação de texto mantém a âncora e as classes do primitivo", () => {
    render(
      <BotaoLink href="/dashboard/atencao" variante="link" tamanho="sm">
        Ver todos
      </BotaoLink>,
    );
    const link = screen.getByRole("link", { name: "Ver todos" });
    expect(link).toHaveAttribute("href", "/dashboard/atencao");
    expect(link.className).toContain("botao-controle");
    expect(link.className).toContain("botao-link");
    expect(link.className).not.toMatch(/\bpx-[1-9]/);
  });
});
