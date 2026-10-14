/**
 * Contexto global de trabalho: a empresa e o mês valem para o sistema inteiro
 * até o operador mudar na barra — sobrevivem à navegação, ao recarregar e
 * viajam no link compartilhado.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mesAtual, mesesAnteriores } from "@/lib/competencia";
import { lerGuardado, mesValido, resolverContexto, sementeDaUrl } from "@/lib/contexto";
import { ProvedorContexto, useContextoGlobal } from "@/components/shell/ProvedorContexto";
import { BarraContexto } from "@/components/shell/BarraContexto";

let buscaAtual = "";
let caminhoAtual = "/dashboard/documentos";
const substituir = vi.fn();
const empurrar = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => caminhoAtual,
  useRouter: () => ({ replace: substituir, push: empurrar }),
  useSearchParams: () => new URLSearchParams(buscaAtual),
}));

vi.mock("@/lib/api", () => ({
  api: {
    listarEmpresas: vi.fn().mockResolvedValue([
      { id: 7, razao_social: "ALFA LTDA", cnpj_cpf: "11111111000111", uf: "SP", ativa: true },
      { id: 42, razao_social: "BETA S.A.", cnpj_cpf: "22222222000122", uf: "MG", ativa: true },
    ]),
  },
  ApiError: class extends Error {},
}));

function Sonda() {
  const contexto = useContextoGlobal();
  return (
    <p data-testid="sonda">
      {contexto.pronto ? "pronto" : "carregando"}|{contexto.empresaId ?? "todas"}|{contexto.mes}|{contexto.competencia}
    </p>
  );
}

beforeEach(() => {
  buscaAtual = "";
  caminhoAtual = "/dashboard/documentos";
  substituir.mockClear();
  empurrar.mockClear();
  window.localStorage.clear();
});

describe("lib/contexto (regras puras)", () => {
  it("só aceita mês bem formado e não futuro", () => {
    expect(mesValido("2026-09")).toBe(true);
    expect(mesValido("09/2026")).toBe(false);
    expect(mesValido("setembro")).toBe(false);
    const [ano, mes] = mesAtual().split("-").map(Number);
    const futuro = `${mes === 12 ? ano + 1 : ano}-${String(mes === 12 ? 1 : mes + 1).padStart(2, "0")}`;
    expect(mesValido(futuro)).toBe(false);
  });

  it("lê a semente da URL e ignora o que é inválido", () => {
    expect(sementeDaUrl("?empresa=42&mes=2026-09")).toEqual({ empresaId: 42, mes: "2026-09" });
    expect(sementeDaUrl("?empresa=abc&mes=xx")).toEqual({ empresaId: null });
    expect(sementeDaUrl("")).toEqual({});
  });

  it("tolerância total com guardado corrompido", () => {
    expect(lerGuardado(null)).toEqual({});
    expect(lerGuardado("não é json")).toEqual({});
    expect(lerGuardado(JSON.stringify({ empresaId: -3, mes: "2099-99" }))).toEqual({});
  });

  it("precedência: URL explícita vence o guardado, que vence o padrão", () => {
    const guardado = JSON.stringify({ empresaId: 7, mes: "2026-08" });
    expect(resolverContexto("?empresa=42&mes=2026-09", guardado)).toEqual({ empresaId: 42, mes: "2026-09" });
    expect(resolverContexto("", guardado)).toEqual({ empresaId: 7, mes: "2026-08" });
    expect(resolverContexto("", null)).toEqual({ empresaId: null, mes: mesAtual() });
  });
});

describe("ProvedorContexto", () => {
  it("resolve o padrão (todas, mês corrente) e espelha na URL", async () => {
    render(
      <ProvedorContexto>
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`pronto|todas|${mesAtual()}`));
    expect(substituir).toHaveBeenCalled();
    const urlEspelhada = String(substituir.mock.calls.at(-1)?.[0] ?? "");
    expect(urlEspelhada).toContain(`mes=${mesAtual()}`);
  });

  it("adota a URL explícita ao montar (deep link)", async () => {
    buscaAtual = "empresa=42&mes=2026-09";
    render(
      <ProvedorContexto>
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|42|2026-09|09/2026"));
  });

  it("adota a URL quando ela muda depois de montado (link de outra tela)", async () => {
    const tela = render(
      <ProvedorContexto>
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|"));
    substituir.mockClear();

    buscaAtual = "mes=2026-09";
    tela.rerender(
      <ProvedorContexto>
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|todas|2026-09"));
  });

  it("persiste no navegador para o próximo acesso", async () => {
    function TrocaMes() {
      const contexto = useContextoGlobal();
      return <button onClick={() => contexto.definirMes("2026-09")}>fixar 09</button>;
    }
    render(
      <ProvedorContexto>
        <TrocaMes />
      </ProvedorContexto>
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "fixar 09" }));
    await waitFor(() => {
      const bruto = window.localStorage.getItem("fluxa:contexto-global") ?? "";
      expect(bruto).toContain("2026-09");
    });
  });
});

describe("BarraContexto", () => {
  it("mostra empresa em destaque e o mês com navegação ‹ ›", async () => {
    render(
      <ProvedorContexto>
        <BarraContexto />
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|"));

    expect(screen.getByRole("combobox", { name: "Empresa" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mês anterior" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Próximo mês" })).toBeDisabled();

    await userEvent.setup().click(screen.getByRole("button", { name: "Mês anterior" }));
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`|${mesesAnteriores(mesAtual(), 1)}`));
  });

  it("filtra a empresa por nome e fixa no contexto", async () => {
    const usuario = userEvent.setup();
    render(
      <ProvedorContexto>
        <BarraContexto />
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|"));

    await usuario.click(screen.getByRole("combobox", { name: "Empresa" }));
    await usuario.click(await screen.findByRole("option", { name: /BETA S\.A\./ }));
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|42|"));
  });

  it("na ficha da empresa, o seletor navega em vez de filtrar", async () => {
    caminhoAtual = "/dashboard/empresa";
    buscaAtual = "id=7";
    const usuario = userEvent.setup();
    render(
      <ProvedorContexto>
        <BarraContexto />
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|"));

    await usuario.click(screen.getByRole("combobox", { name: "Empresa" }));
    await usuario.click(await screen.findByRole("option", { name: /BETA S\.A\./ }));
    expect(empurrar).toHaveBeenCalledWith("/dashboard/empresa?id=42");
  });
});
