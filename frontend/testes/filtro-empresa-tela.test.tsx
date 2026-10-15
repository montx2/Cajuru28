/**
 * Empresa é filtro de tela, com busca por nome/CNPJ, e não um recorte global
 * escondido. Foi o que a barra fixa antiga tentou ser: um único "empresa" na
 * URL servido pela barra e pelas telas ao mesmo tempo, cada uma escrevendo com
 * uma intenção — e a tela piscando. Aqui o filtro é da fila de atenção: vale
 * para os alertas e para mais nada.
 */
import { useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProvedorContexto } from "@/components/shell/ProvedorContexto";
import { Atencao } from "@/app/dashboard/atencao/Atencao";

const rota = vi.hoisted(() => ({
  caminho: "/dashboard/atencao",
  busca: "",
  cacheBusca: "\u0000",
  cache: new URLSearchParams(""),
  ouvintes: new Set<() => void>(),
  aplicadas: [] as string[],
}));

function notificar() {
  for (const ouvinte of Array.from(rota.ouvintes)) ouvinte();
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
      if (caminho === rota.caminho && busca === rota.busca) return;
      window.history.replaceState({}, "", url);
      rota.caminho = caminho;
      rota.busca = busca;
      rota.aplicadas.push(url);
      notificar();
    },
    push: vi.fn(),
  }),
}));

function inscrever(ouvinte: () => void) {
  rota.ouvintes.add(ouvinte);
  return () => rota.ouvintes.delete(ouvinte);
}

vi.mock("@/lib/api", () => ({
  api: {
    alertas: vi.fn().mockResolvedValue({
      total: 2,
      criticos: 1,
      atencao: 1,
      infos: 0,
      itens: [
        { id: "a1", nivel: "critico", categoria: "certificado", titulo: "Certificado A1 vence em 5 dias", detalhe: "ALFA LTDA · 11.111.111/0001-11", empresa_id: 7, empresa_razao_social: "ALFA LTDA", acao_rotulo: null, acao_href: null },
        { id: "a2", nivel: "atencao", categoria: "sincronismo", titulo: "BETA S.A. está sem captura há 3 dias", detalhe: "A janela da SEFAZ liberou e nada foi importado", empresa_id: 42, empresa_razao_social: "BETA S.A.", acao_rotulo: null, acao_href: null },
      ],
    }),
    listarEmpresas: vi.fn().mockResolvedValue([
      { id: 7, razao_social: "ALFA LTDA", cnpj_cpf: "11111111000111", uf: "SP", ativa: true, criado_em: "2026-01-01T00:00:00Z" },
      { id: 42, razao_social: "BETA S.A.", cnpj_cpf: "22222222000122", uf: "MG", ativa: true, criado_em: "2026-01-01T00:00:00Z" },
    ]),
  },
  ApiError: class extends Error {},
}));

vi.mock("@/components/shell/ProvedorAlertas", () => ({
  useContagemAlertas: () => ({ contagem: { total: 2, criticos: 1, atencao: 1 }, carregando: false, erro: null, atualizar: vi.fn() }),
}));

beforeEach(() => {
  rota.caminho = "/dashboard/atencao";
  rota.busca = "";
  rota.cacheBusca = "\u0000";
  rota.aplicadas.length = 0;
  window.history.replaceState({}, "", rota.caminho);
  window.localStorage.clear();
});

function abrir() {
  return render(
    <ProvedorContexto>
      <Atencao />
    </ProvedorContexto>
  );
}

describe("filtro de empresa da fila de atenção", () => {
  it("mostra as duas empresas sem filtro e só a pedida com ?empresa=", async () => {
    const { unmount } = abrir();
    await waitFor(() => expect(screen.getByText("Certificado A1 vence em 5 dias")).toBeInTheDocument());
    expect(screen.getByText("BETA S.A. está sem captura há 3 dias")).toBeInTheDocument();
    unmount();

    rota.busca = "empresa=42";
    window.history.replaceState({}, "", `${rota.caminho}?${rota.busca}`);
    abrir();

    await waitFor(() => expect(screen.getByText("BETA S.A. está sem captura há 3 dias")).toBeInTheDocument());
    expect(screen.queryByText("Certificado A1 vence em 5 dias")).not.toBeInTheDocument();
    // O filtro é da tela: não inventa competência nem toca no contexto global.
    expect(rota.busca).toBe("empresa=42");
  });

  it("encontra a empresa pelo CNPJ e escreve só o parâmetro da tela", async () => {
    abrir();
    await waitFor(() => expect(screen.getByText("Certificado A1 vence em 5 dias")).toBeInTheDocument());

    const campo = screen.getByRole("combobox", { name: "Empresa" });
    await userEvent.setup().click(campo);
    await userEvent.setup().type(campo, "22222222000122");
    await userEvent.setup().click(await screen.findByRole("option", { name: /BETA S\.A\./ }));

    await waitFor(() => expect(rota.aplicadas).toEqual(["/dashboard/atencao?empresa=42"]));
    await waitFor(() => expect(screen.queryByText("Certificado A1 vence em 5 dias")).not.toBeInTheDocument());
    expect(screen.getByText("BETA S.A. está sem captura há 3 dias")).toBeInTheDocument();
  });
});
