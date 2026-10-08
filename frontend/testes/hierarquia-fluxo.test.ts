/**
 * Guardas de hierarquia e fluxo (Bloco B da auditoria).
 *
 * São invariantes de tela que não dependem de render: a auditoria mostrou que
 * a empresa abria na aba errada, o alerta mandava para a tela genérica, o
 * vazio dizia "dispare a captura" sem dar o caminho e a descrição de um cartão
 * expunha rota interna. Cada teste aqui trava um desses consertos para a
 * próxima refatoração não devolver o problema em silêncio.
 *
 * O que entra: ordem/default de abas, uma ação primária por tela, vazio com
 * próximo passo, e nada de rota interna em texto de interface.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

function fonte(caminho: string): string {
  return readFileSync(resolve(__dirname, "..", caminho), "utf-8");
}

function normalizado(caminho: string): string {
  return fonte(caminho).replace(/\s+/g, " ");
}

describe("Empresa: a página abre no que se veio ver", () => {
  const empresa = fonte("app/dashboard/empresa/Empresa.tsx");

  it("a primeira aba é Documentos e Dados é a última", () => {
    const ordem = empresa.match(/const ABAS = \[([^\]]+)\]/)?.[1] ?? "";
    const abas = [...ordem.matchAll(/"([a-z]+)"/g)].map((achado) => achado[1]);
    expect(abas[0]).toBe("documentos");
    expect(abas.at(-1)).toBe("dados");
    expect(new Set(abas).size).toBe(abas.length);
  });

  it("sem ?aba= o fallback também é documentos", () => {
    expect(normalizado("app/dashboard/empresa/Empresa.tsx")).toContain('ler("aba") : "documentos"');
  });

  it("a ordem exibida segue a mesma ordem de uso", () => {
    const abas = [...empresa.replace(/\s+/g, " ").matchAll(/valor: "([a-z]+)", rotulo:/g)].map(
      (achado) => achado[1]
    );
    expect(abas).toEqual(["documentos", "sincronismo", "certificado", "execucoes", "dados"]);
  });
});

describe("uma ação primária por tela", () => {
  it("Importações não mostra duas primárias de disparo com a prévia aberta", () => {
    const arquivo = normalizado("app/dashboard/importacoes/Importacoes.tsx");
    expect(arquivo).toContain('variante={resultado ? "secundaria" : "primaria"}');
  });
});

describe("vazio que manda para outra tela traz o caminho", () => {
  const telas = [
    "app/dashboard/documentos/Documentos.tsx",
    "app/dashboard/empresa/Empresa.tsx",
    "app/dashboard/empresas/Empresas.tsx",
    "app/dashboard/certificados/Certificados.tsx",
    "app/dashboard/relatorios/Relatorios.tsx",
    "app/dashboard/execucoes/Execucoes.tsx",
    "app/dashboard/importacoes/Importacoes.tsx",
  ];

  /** Instruções curtas que aparecem logo depois de um `vazioInstrucao:`. */
  function instrucoesDeVazio(texto: string): string[] {
    const encontradas: string[] = [];
    let posicao = texto.indexOf("vazioInstrucao:");
    while (posicao >= 0) {
      const janela = texto.slice(posicao, posicao + 320);
      for (const achado of janela.matchAll(/"([^"]{20,})"/g)) encontradas.push(achado[1]);
      posicao = texto.indexOf("vazioInstrucao:", posicao + 1);
    }
    return encontradas;
  }

  // Verbo que manda o operador para outro lugar: o caminho precisa existir ali.
  const MANDA_PARA_FORA = /(dispare|disparar|cadastre|troque o filtro|convide|envie o a1)/i;

  it.each(telas)("%s: instrução de ir a outro lugar tem ação clicável", (caminho) => {
    const texto = normalizado(caminho);
    const instrucoes = instrucoesDeVazio(texto);
    expect(instrucoes.length, `nenhuma instrução de vazio lida em ${caminho} — leitura desatualizada`).toBeGreaterThan(0);

    const externas = instrucoes.filter((instrucao) => MANDA_PARA_FORA.test(instrucao));
    if (externas.length === 0) return;
    expect(texto, `vazio manda para fora sem ação em ${caminho}: ${externas[0].slice(0, 70)}…`).toContain("vazioAcao");
  });
});

describe("interface não expõe rota interna", () => {
  it.each(["app/dashboard/saude/Saude.tsx", "app/dashboard/configuracoes/Configuracoes.tsx"])(
    "%s: nenhuma descrição cita caminho de API",
    (caminho) => {
      const texto = fonte(caminho);
      const descricoes = [...texto.matchAll(/descricao="([^"]*)"/g)].map((achado) => achado[1]);
      const vazamentos = descricoes.filter((descricao) => /(^|\s)\/[a-z_-]+(\/[a-z_0-9-]+)*/.test(descricao));
      expect(vazamentos, `descrição com rota: ${vazamentos.join(" | ")}`).toEqual([]);
    }
  );
});
