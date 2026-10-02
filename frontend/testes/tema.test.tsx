import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CHAVE_TEMA, SCRIPT_TEMA_INICIAL, ehTemaEscuro, normalizarTema } from "@/lib/preferenciaTema";
import { lerTema, useTema } from "@/lib/tema";

let sistemaEscuro = false;
const ouvintes = new Set<() => void>();

beforeEach(() => {
  localStorage.clear();
  sistemaEscuro = false;
  ouvintes.clear();
  delete document.documentElement.dataset.tema;
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    get matches() { return sistemaEscuro; },
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_tipo: string, ouvinte: () => void) => ouvintes.add(ouvinte),
    removeEventListener: (_tipo: string, ouvinte: () => void) => ouvintes.delete(ouvinte),
  })));
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.tema;
});

function mudarSistema(escuro: boolean) {
  act(() => {
    sistemaEscuro = escuro;
    ouvintes.forEach((ouvinte) => ouvinte());
  });
}

describe("tema Grafite & Menta", () => {
  it("começa escuro mesmo quando o sistema operacional está claro", () => {
    expect(normalizarTema(null)).toBe("escuro");
    expect(normalizarTema("preferencia-invalida")).toBe("escuro");
    expect(lerTema()).toBe("escuro");
    expect(ehTemaEscuro("escuro", false)).toBe(true);
  });

  it.each([
    [null, false, "escuro"],
    ["invalido", false, "escuro"],
    ["escuro", false, "escuro"],
    ["claro", true, "claro"],
    ["sistema", false, "claro"],
    ["sistema", true, "escuro"],
  ])("a primeira pintura respeita %s e sistema=%s", (salvo, sistema, esperado) => {
    sistemaEscuro = sistema;
    if (salvo) localStorage.setItem(CHAVE_TEMA, salvo);
    window.eval(SCRIPT_TEMA_INICIAL);
    expect(document.documentElement.dataset.tema).toBe(esperado);
    // O script só pinta; não deixa um listener preso à preferência inicial.
    expect(ouvintes.size).toBe(0);
  });

  it("continua funcionando quando o navegador bloqueia o armazenamento", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("bloqueado"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("bloqueado"); });
    expect(lerTema()).toBe("escuro");
    window.eval(SCRIPT_TEMA_INICIAL);
    expect(document.documentElement.dataset.tema).toBe("escuro");
    const { result } = renderHook(useTema);
    act(() => result.current.definir("claro"));
    expect(result.current.tema).toBe("claro");
    expect(document.documentElement.dataset.tema).toBe("claro");
  });

  it("persistência e mudanças do sistema não sobrescrevem uma escolha explícita", () => {
    const { result } = renderHook(useTema);
    act(() => result.current.definir("claro"));
    expect(localStorage.getItem(CHAVE_TEMA)).toBe("claro");
    mudarSistema(true);
    expect(result.current.escuro).toBe(false);
    expect(document.documentElement.dataset.tema).toBe("claro");
    act(() => result.current.definir("sistema"));
    expect(result.current.escuro).toBe(true);
    mudarSistema(false);
    expect(result.current.tema).toBe("sistema");
    expect(result.current.escuro).toBe(false);
  });

  it("sincroniza dois seletores na mesma aba mesmo sem localStorage", () => {
    const primeiro = renderHook(useTema);
    const segundo = renderHook(useTema);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("bloqueado"); });
    act(() => primeiro.result.current.definir("claro"));
    expect(segundo.result.current.tema).toBe("claro");
  });

  it("sincroniza a escolha feita em outra aba e remove listeners ao desmontar", () => {
    const { result, unmount } = renderHook(useTema);
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: CHAVE_TEMA, newValue: "claro" })));
    expect(result.current.tema).toBe("claro");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: CHAVE_TEMA, newValue: null })));
    expect(result.current.tema).toBe("escuro");
    unmount();
    expect(ouvintes.size).toBe(0);
  });
});
