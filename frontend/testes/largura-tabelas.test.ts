/**
 * Guarda de largura das tabelas.
 *
 * Sem navegador não há medida de pixel na tela; o que dá para fixar é o piso
 * que cada coluna impõe — `largura` declarada ou o padrão da `Tabela`
 * (`min-w-32` numérica, `min-w-24` de texto), mais o padding da célula (px-3) e
 * a coluna de seleção. O piso somado precisa caber na largura útil de um
 * notebook de 1440 px: 1440 − 256 da lateral − 64 do padding = 1120 px.
 *
 * A tabela rola por dentro do próprio contêiner, então isso não quebra a
 * página — mas uma tela que rola em 1440 está escondendo coluna de gente que
 * trabalha nela o dia inteiro, e foi exatamente o que aconteceu no acervo.
 * Se este teste falhar depois de uma refatoração legítima (por exemplo, a
 * tela deixar de montar `colunas` inline), ajuste a leitura abaixo — não o
 * limite — só depois de medir de novo com `python3 scripts/medir_tabelas.py`.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ESPACO = 4;
const PADDING_CELULA = 24; // px-3
const COLUNA_SELECAO = 40; // w-10 + px-2
const LARGURA_UTIL_1440 = 1120; // 1440 − 256 (lateral) − 64 (lg:px-8)

function px(classe: string): number {
  const emRem = classe.match(/^(?:min-)?w-\[([\d.]+)rem\]$/);
  if (emRem) return Math.round(Number(emRem[1]) * 16);
  const emEspacos = classe.match(/^(?:min-)?w-(\d+)$/);
  if (emEspacos) return Number(emEspacos[1]) * ESPACO;
  return 0;
}

function larguraMinima(classe: string): number {
  return Math.max(...classe.split(/\s+/).map(px), 0);
}

interface Coluna {
  id: string;
  largura: string | null;
  numerica: boolean;
  oculta: boolean;
  fixa: boolean;
}

function colunasDe(caminho: string): Coluna[] {
  const texto = readFileSync(resolve(__dirname, "..", caminho), "utf-8");
  const inicio = texto.indexOf("const colunas");
  expect(inicio, `não achei o array 'colunas' em ${caminho}`).toBeGreaterThan(-1);
  return texto
    .slice(inicio)
    .split(/\n {6}\{\n/)
    .map((bloco) => {
      const id = bloco.match(/id: "([^"]+)"/)?.[1];
      if (!id) return null;
      return {
        id,
        largura: bloco.match(/largura: "([^"]+)"/)?.[1] ?? null,
        numerica: /numerica: true/.test(bloco),
        oculta: /ocultaPorPadrao: true/.test(bloco),
        fixa: /^\s{8}fixa: true/m.test(bloco),
      };
    })
    .filter((coluna): coluna is Coluna => coluna !== null);
}

function piso(caminho: string, selecao = false): number {
  const colunas = colunasDe(caminho);
  expect(colunas.length, `poucas colunas lidas em ${caminho} — leitura desatualizada`).toBeGreaterThanOrEqual(4);
  return colunas
    .filter((coluna) => coluna.fixa || !coluna.oculta)
    .reduce((total, coluna) => {
      const classe = coluna.largura ?? (coluna.numerica ? "min-w-32" : "min-w-24");
      return total + larguraMinima(classe) + PADDING_CELULA;
    }, selecao ? COLUNA_SELECAO : 0);
}

describe("largura das tabelas", () => {
  it("acervo de documentos cabe em tela de 1440 px sem rolar de lado", () => {
    expect(piso("app/dashboard/documentos/Documentos.tsx", true)).toBeLessThanOrEqual(LARGURA_UTIL_1440);
  });

  it.each([
    ["empresas", "app/dashboard/empresas/Empresas.tsx"],
    ["execuções", "app/dashboard/execucoes/Execucoes.tsx"],
    ["certificados", "app/dashboard/certificados/Certificados.tsx"],
    ["usuários", "app/dashboard/usuarios/Usuarios.tsx"],
    ["auditoria", "app/dashboard/auditoria/Auditoria.tsx"],
  ])("tela de %s cabe em 1440 px", (_nome, caminho) => {
    expect(piso(caminho)).toBeLessThanOrEqual(LARGURA_UTIL_1440);
  });
});
