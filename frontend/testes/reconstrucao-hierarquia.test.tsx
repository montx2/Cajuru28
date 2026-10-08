import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

function fonte(caminho: string): string {
  const raizFrontend = process.cwd().endsWith("frontend") ? process.cwd() : resolve(process.cwd(), "frontend");
  return readFileSync(resolve(raizFrontend, caminho), "utf8");
}

function emOrdem(codigo: string, trechos: string[]) {
  const posicoes = trechos.map((trecho) => codigo.indexOf(trecho));
  expect(posicoes.every((posicao) => posicao >= 0)).toBe(true);
  expect(posicoes).toEqual([...posicoes].sort((a, b) => a - b));
}

describe("hierarquia operacional reconstruída", () => {
  it("mantém decisões, execuções, KPIs, análise recolhida e infraestrutura nesta ordem no Painel", () => {
    const codigo = fonte("app/dashboard/Painel.tsx");

    emOrdem(codigo, [
      'titulo="Precisa da sua atenção"',
      'titulo="Execuções agora"',
      'id="titulo-numeros-mes"',
      '<details',
      '<footer',
    ]);
    expect(codigo).toContain('pendencias > 0 ? (');
    expect(codigo).toContain('Ver {contagem(pendencias, "pendência", "pendências")}');
    expect(codigo).not.toContain('href="/dashboard/importacoes"');
  });

  it("mantém o sincronismo antes do disparo e o XML externo somente no menu de Importações", () => {
    const codigo = fonte("app/dashboard/importacoes/Importacoes.tsx");

    emOrdem(codigo, ['titulo="Captura automática"', 'titulo="Período e tipos"', 'titulo="Empresas"']);
    expect(codigo).toContain('rotulo: "Importar XMLs de outro sistema…"');
    expect(codigo).toContain("<ModalImportarXmls");
    expect(codigo).not.toContain("<ImportarXmls");
    expect(codigo).not.toMatch(/titulo="[12] ·/);
  });

  it("preserva a dieta e a descoberta contextual em Documentos e Empresas", () => {
    const documentos = fonte("app/dashboard/documentos/Documentos.tsx");
    const empresas = fonte("app/dashboard/empresas/Empresas.tsx");

    expect(documentos).toContain('rotulo="Buscar documento"');
    expect(documentos).toContain('rotulo="Filtros"');
    expect(documentos).toContain('rotulo="Exportar"');
    expect(documentos).toContain('rotulo="Mais ações da tabela"');
    expect(documentos).toContain("Baixar {numero(quantidade)} XMLs");
    // A exclusão em lote saiu do lado do botão principal e foi para o "⋯":
    // destrutiva, rara e vizinha de clique por engano na barra de seleção.
    expect(documentos).toContain('rotulo="Mais ações da seleção"');
    expect(documentos).toContain('Excluir ${contagem(quantidade, "documento", "documentos")}…');
    expect(documentos).not.toContain(">Excluir {numero(quantidade)}…<");

    expect(empresas).toContain('rotulo="Buscar empresa"');
    expect(empresas).toContain("Nova empresa");
    expect(empresas).toContain('rotulo="Mais ações e filtros"');
    expect(empresas).toContain('rotulo: "Importar certificados em lote…"');
    expect(empresas).toContain('rotulo: "Importar XMLs de outro sistema…"');
    expect(empresas).not.toContain("aoMudarDensidade={setDensidade}");
    expect(empresas).not.toContain("aoMudarColunas=");
  });

  it("não deixa refresh textual nem ajuda permanente de fornecedor nas superfícies revisadas", () => {
    const telas = [
      "app/dashboard/atencao/Atencao.tsx",
      "app/dashboard/auditoria/Auditoria.tsx",
      "app/dashboard/certificados/Certificados.tsx",
      "app/dashboard/configuracoes/Configuracoes.tsx",
      "app/dashboard/execucoes/Execucoes.tsx",
      "app/dashboard/saude/Saude.tsx",
      "app/dashboard/usuarios/Usuarios.tsx",
    ].map(fonte);

    for (const codigo of telas) {
      expect(codigo).not.toMatch(/>\s*Atualizar\s*<\/Botao>/);
    }
  });
});
