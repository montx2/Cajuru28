import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const raiz = process.cwd().endsWith("frontend") ? process.cwd() : resolve(process.cwd(), "frontend");
const css = readFileSync(resolve(raiz, "app/globals.css"), "utf8");

function luminancia(hex: string): number {
  const canais = [1, 3, 5].map((inicio) => parseInt(hex.slice(inicio, inicio + 2), 16) / 255);
  const [r, g, b] = canais.map((canal) => canal <= 0.04045 ? canal / 12.92 : ((canal + 0.055) / 1.055) ** 2.4);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contraste(a: string, b: string): number {
  const [menor, maior] = [luminancia(a), luminancia(b)].sort((x, y) => x - y);
  return (maior + 0.05) / (menor + 0.05);
}

describe("contraste dos tokens reais, sem reduzir opacidade do texto", () => {
  it.each(["escuro", "claro"])("mantém legibilidade e contornos no tema %s", (tema) => {
    const bloco = css.match(new RegExp(`\\[data-tema="${tema}"\\]\\s*\\{([\\s\\S]*?)\\}`))?.[1];
    expect(bloco).toBeTruthy();
    const tokens = Object.fromEntries(Array.from(bloco!.matchAll(/--([\w-]+):\s*(#[\da-f]{6})/gi), (item) => [item[1], item[2]]));
    for (const [nome, hex] of Object.entries(tokens)) {
      const rgb = bloco!.match(new RegExp(`--${nome}-rgb:\\s*([\\d ]+);`))?.[1];
      if (rgb) expect(rgb.trim(), `${tema}: hex/RGB de ${nome}`).toBe([1, 3, 5].map((inicio) => parseInt(hex.slice(inicio, inicio + 2), 16)).join(" "));
    }
    for (const fundo of ["fundo", "fundo-afundado", "superficie", "superficie-alta"]) {
      for (const tinta of ["tinta-forte", "tinta", "tinta-suave", "tinta-fraca", "acento", "erro", "espera", "ok", "info"]) {
        expect(contraste(tokens[tinta], tokens[fundo]), `${tema}: ${tinta} sobre ${fundo}`).toBeGreaterThanOrEqual(4.5);
      }
      expect(contraste(tokens["borda-controle"], tokens[fundo]), `${tema}: contorno sobre ${fundo}`).toBeGreaterThanOrEqual(3);
    }
    for (const estado of ["acento", "erro", "espera"]) {
      expect(contraste(tokens[`${estado}-contraste`], tokens[estado]), `${tema}: texto sobre ${estado}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
