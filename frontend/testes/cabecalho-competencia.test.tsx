/**
 * O topo do produto tem um dono só: a competência. Foi assim que a empresa
 * saiu da faixa fixa — ela é filtro de tela, e um seletor global no cabeçalho
 * virava um filtro invisível que o operador não conseguia relacionar com o que
 * estava vendo (e que, escrito pela barra e pelas telas ao mesmo tempo, fazia a
 * tela piscar).
 */
import { useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Shell } from "@/components/shell/Shell";

const rota = vi.hoisted(() => ({ caminho: "/dashboard/documentos", busca: "", cacheBusca: "\u0000", cache: new URLSearchParams(""), ouvintes: new Set<() => void>() }));

function notificar() {
  for (const ouvinte of Array.from(rota.ouvintes)) ouvinte();
}

function inscrever(ouvinte: () => void) {
  rota.ouvintes.add(ouvinte);
  return () => rota.ouvintes.delete(ouvinte);
}

vi.mock("next/navigation", () => ({
  usePathname: () => useSyncExternalStore(inscrever, () => rota.caminho, () => rota.caminho),
  useSearchParams: () =>
    useSyncExternalStore(
      inscrever,
      () => {
        if (rota.cacheBusca !== rota.busca) {
          rota.cacheBusca = rota.busca;
          rota.cache = new URLSearchParams(rota.busca);
        }
        return rota.cache;
      },
      () => rota.cache
    ),
  useRouter: () => ({
    replace: (url: string) => {
      const [caminho, busca = ""] = url.split("?");
      rota.caminho = caminho;
      rota.busca = busca;
      window.history.replaceState({}, "", url);
      notificar();
    },
    push: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    quemSouEu: vi.fn().mockResolvedValue({ id: 1, nome: "Marina Alves", email: "marina@escritorio.com.br", papel: "admin", escritorio_id: 1, escritorio_nome: "Escritório Alves" }),
    contagemAlertas: vi.fn().mockResolvedValue({ total: 0, criticos: 0, atencao: 0 }),
    listarEmpresas: vi.fn().mockResolvedValue([{ id: 7, razao_social: "ALFA LTDA", cnpj_cpf: "11111111000111", uf: "SP", ativa: true, criado_em: "2026-01-01T00:00:00Z" }]),
  },
  ApiError: class extends Error {},
}));

beforeEach(() => {
  rota.caminho = "/dashboard/documentos";
  rota.busca = "mes=2026-09&empresa=7";
  rota.cacheBusca = "\u0000";
  window.history.replaceState({}, "", `${rota.caminho}?${rota.busca}`);
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

describe("cabeçalho do workspace", () => {
  it("mostra a competência (com o mês da URL) e não tem seletor de empresa", async () => {
    render(
      <Shell>
        <p>conteúdo</p>
      </Shell>
    );

    const competencia = await screen.findByRole("button", { name: /competência/i });
    await waitFor(() => expect(competencia).toHaveTextContent("setembro/2026"));
    expect(competencia).toHaveAttribute("aria-haspopup", "dialog");

    // Empresa: nenhum campo no topo — o `?empresa=7` é da tela, não do shell.
    expect(screen.queryByRole("combobox", { name: "Empresa" })).not.toBeInTheDocument();
    expect(document.querySelector("[class*='top-[var(--altura-cabecalho)]']")).toBeNull();
  });
});
