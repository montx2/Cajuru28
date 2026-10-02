import { renderToString } from "react-dom/server";
import { hydrateRoot, type Root } from "react-dom/client";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { usePreferencia } from "@/lib/usePreferencia";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

it("hidrata com o mesmo padrão do servidor antes de restaurar o menu recolhido", async () => {
  localStorage.setItem("fluxa:menu-colapsado", "true");
  function Preferencia() {
    const [colapsada] = usePreferencia("menu-colapsado", false);
    return <span data-colapsada={String(colapsada)}>Navegação</span>;
  }
  const html = renderToString(<Preferencia />);
  expect(html).toContain('data-colapsada="false"');
  const container = document.createElement("div");
  container.innerHTML = html;
  document.body.appendChild(container);
  const erro = vi.spyOn(console, "error").mockImplementation(() => undefined);
  let root: Root;
  await act(async () => { root = hydrateRoot(container, <Preferencia />); });
  expect(container.firstElementChild).toHaveAttribute("data-colapsada", "true");
  expect(erro).not.toHaveBeenCalled();
  await act(async () => root.unmount());
  container.remove();
});

it("mantém persistência, setters funcionais e fallback de armazenamento inválido/bloqueado", () => {
  localStorage.setItem("fluxa:menu-colapsado", "JSON quebrado");
  const { result } = renderHook(() => usePreferencia("menu-colapsado", false));
  expect(result.current[0]).toBe(false);
  act(() => result.current[1]((atual) => !atual));
  expect(result.current[0]).toBe(true);
  expect(localStorage.getItem("fluxa:menu-colapsado")).toBe("true");
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("bloqueado"); });
  act(() => result.current[1](false));
  expect(result.current[0]).toBe(false);
});
