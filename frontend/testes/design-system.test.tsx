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
import { Aviso } from "@/components/ui/Aviso";
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

/**
 * Tabela: duas peles declaradas no CSS (`.tabela-dados` na tela,
 * `.tabela-impressao` no papel) e uma caixa que rola por dentro
 * (`.caixa-tabela`). O que era skin copiada sai da tela.
 */
describe("toda tabela tem pele declarada", () => {
  /** `sr-only`: gêmeo acessível de um gráfico, não é tabela de leitura. */
  const SEM_PELE = ["components/fiscal/Graficos.tsx"];
  /** O primitivo da tabela grande define a própria pele. */
  const PRIMITIVO = "components/ui/Tabela.tsx";

  it("nenhuma tabela crua volta a ser desenhada por conta própria", () => {
    const infratores: string[] = [];
    for (const arquivo of arquivosTsx(["app", "components"])) {
      const relativo = arquivo.slice(RAIZ.length + 1).replace(/\\/g, "/");
      if (relativo === PRIMITIVO || SEM_PELE.includes(relativo)) continue;
      const conteudo = readFileSync(arquivo, "utf8");
      for (const [, classes] of conteudo.matchAll(/<table className="([^"]*)"/g)) {
        if (!classes.includes("tabela-dados") && !classes.includes("tabela-impressao")) {
          infratores.push(`${relativo}: <table className="${classes}">`);
        }
      }
      if (/<table(?![^>]*className)/.test(conteudo)) infratores.push(`${relativo}: <table> sem classe`);
    }
    expect(infratores).toEqual([]);
  });

  it("a caixa que rola não é remontada à mão", () => {
    const infratores: string[] = [];
    for (const arquivo of arquivosTsx(["app", "components"])) {
      const conteudo = readFileSync(arquivo, "utf8");
      // assinatura antiga: `<div>` com rolagem fina, altura máxima e traço à mão.
      // (`<pre>` de stack trace também rola, mas não é caixa de tabela.)
      for (const [linha, texto] of conteudo.split("\n").entries()) {
        if (/<div className="[^"]*rolagem-fina[^"]*max-h-/.test(texto) && /border border-traco/.test(texto)) {
          const relativo = arquivo.slice(RAIZ.length + 1).replace(/\\/g, "/");
          infratores.push(`${relativo}:${linha + 1}`);
        }
      }
    }
    expect(infratores, 'Use <div className="caixa-tabela max-h-…">').toEqual([]);
  });

  it("a pele e a caixa existem no CSS, com a especificidade baixa que permite a tela ajustar", () => {
    const css = readFileSync(resolve(RAIZ, "app/globals.css"), "utf8");
    for (const classe of [".tabela-dados", ".tabela-impressao", ".caixa-tabela", ".superficie-plana"]) {
      expect(css, classe).toContain(classe);
    }
    // `:where()` mantém a regra em 0-1-0: `text-right`/`py-4` da tela vencem.
    expect(css).toMatch(/\.tabela-dados :where\(/);
  });
});

/**
 * Mensagem: 14 lugares reescreviam a mesma caixa vermelha à mão — cinco com
 * ícone, dois como texto solto (o mesmo erro sem caixa, em outra tela), e cada
 * um com a própria combinação de padding. Duas peças passam a ser donas disso:
 * `Aviso` (resultado da ação) e `ErroDoCampo` (o que houve no controle).
 */
describe("mensagem de erro tem dono", () => {
  /** Primitivos e shell: são eles que emitem a região viva para o resto. */
  const DONOS = ["components/ui/", "components/shell/"];

  it("caixa vermelha à mão não volta", () => {
    const infratores: string[] = [];
    for (const arquivo of arquivosTsx(["app", "components"])) {
      const relativo = arquivo.slice(RAIZ.length + 1).replace(/\\/g, "/");
      if (DONOS.some((prefixo) => relativo.startsWith(prefixo))) continue;
      const conteudo = readFileSync(arquivo, "utf8");
      if (conteudo.includes("border-erro/40")) infratores.push(relativo);
    }
    expect(infratores, 'Use <Aviso tom="erro" …> ou <ErroDoCampo>.').toEqual([]);
  });

  it("região viva (role=alert/status) só sai de components/ui e components/shell", () => {
    const infratores: string[] = [];
    for (const arquivo of arquivosTsx(["app", "components"])) {
      const relativo = arquivo.slice(RAIZ.length + 1).replace(/\\/g, "/");
      if (DONOS.some((prefixo) => relativo.startsWith(prefixo))) continue;
      const conteudo = readFileSync(arquivo, "utf8");
      if (/role="(alert|status)"/.test(conteudo)) infratores.push(relativo);
    }
    expect(infratores, "A região viva é do primitivo (`Aviso`, `ErroDoCampo`, `Toast`).").toEqual([]);
  });

  it("ErroDoCampo é o mesmo nos dois lugares que o usam", () => {
    const campo = readFileSync(resolve(RAIZ, "components/ui/Campo.tsx"), "utf8");
    expect(campo).toContain("export function ErroDoCampo");
    // quem aponta o erro de um controle composto usa o primitivo, não um clone
    for (const caminho of ["components/fiscal/SeletorPeriodo.tsx", "app/dashboard/empresas/Empresas.tsx"]) {
      expect(readFileSync(resolve(RAIZ, caminho), "utf8"), caminho).toContain("<ErroDoCampo");
    }
  });

  it("o aviso anuncia conforme a urgência — sem repetir isso em cada tela", () => {
    const { unmount } = render(
      <Aviso tom="erro" urgente>
        Falhou
      </Aviso>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Falhou");
    unmount();
    render(
      <Aviso tom="espera" data-situacao="documento">
        Aguardando
      </Aviso>,
    );
    // Sem `urgente` é `role="status"`: expirar ou aguardar não interrompe a leitura.
    expect(screen.getByRole("status")).toHaveTextContent("Aguardando");
    // `data-*` de quem usa o aviso (a ficha marca o bloco de situação assim).
    expect(screen.getByRole("status")).toHaveAttribute("data-situacao", "documento");
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
