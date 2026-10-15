/**
 * Competência global: o mês de trabalho vale para o sistema inteiro até o
 * operador mudar no cabeçalho — sobrevive à navegação, ao recarregar e viaja
 * no link compartilhado.
 *
 * Aqui também moram os dois testes de regressão do bug que derrubou a barra
 * fixa antiga: a tela piscando e trocando os números sozinha. A causa era a
 * URL com dois donos — o provedor espelhava o estado de volta para a barra de
 * endereço enquanto as telas escreviam os mesmos parâmetros com outra
 * intenção. Um ciclo A→B→A é detectável: alguma URL precisa se repetir.
 */
import { useEffect } from "react";
import { useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mesAtual, mesesAnteriores } from "@/lib/competencia";
import { lerGuardado, mesValido, resolverContexto, sementeDaUrl } from "@/lib/contexto";
import { useUrlEstado } from "@/lib/urlEstado";
import { ProvedorContexto, useContextoGlobal } from "@/components/shell/ProvedorContexto";
import { SeletorCompetencia } from "@/components/shell/SeletorCompetencia";

/** Roteador de mentira que se comporta como o real: escrever muda a URL e a tela. */
const rota = vi.hoisted(() => ({
  caminho: "/dashboard/documentos",
  busca: "",
  cacheBusca: "\u0000",
  cache: new URLSearchParams(""),
  ouvintes: new Set<() => void>(),
  /** Toda escrita pedida, inclusive as que não mudaram nada. */
  escritas: [] as string[],
  /** URLs efetivamente aplicadas, em ordem — é aqui que um laço apareceria. */
  aplicadas: [] as string[],
}));

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
      rota.escritas.push(url);
      const [caminho, busca = ""] = url.split("?");
      if (caminho === rota.caminho && busca === rota.busca) return;
      // `history.replaceState` de verdade: `window.location` acompanha a URL,
      // exatamente como no navegador.
      window.history.replaceState({}, "", url);
      rota.caminho = caminho;
      rota.busca = busca;
      rota.aplicadas.push(url);
      notificar();
    },
    push: (url: string) => {
      rota.escritas.push(url);
      window.history.replaceState({}, "", url);
      const [caminho, busca = ""] = url.split("?");
      rota.caminho = caminho;
      rota.busca = busca;
      rota.aplicadas.push(url);
      notificar();
    },
  }),
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
  const { ler } = useUrlEstado();
  return (
    <p data-testid="sonda">
      {contexto.pronto ? "pronto" : "carregando"}|{contexto.mes}|{contexto.competencia}|{ler("empresa") || "todas"}
    </p>
  );
}

beforeEach(() => {
  rota.caminho = "/dashboard/documentos";
  rota.busca = "";
  rota.cacheBusca = "\u0000";
  rota.escritas.length = 0;
  rota.aplicadas.length = 0;
  window.history.replaceState({}, "", rota.caminho);
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
    expect(sementeDaUrl("?mes=2026-09")).toEqual({ mes: "2026-09" });
    expect(sementeDaUrl("?mes=xx&empresa=42")).toEqual({});
    expect(sementeDaUrl("")).toEqual({});
  });

  it("tolerância total com guardado corrompido — e sem empresa nenhuma", () => {
    expect(lerGuardado(null)).toEqual({});
    expect(lerGuardado("não é json")).toEqual({});
    expect(lerGuardado(JSON.stringify({ mes: "2099-99" }))).toEqual({});
    // Guardado de versão anterior, quando a empresa era global: o mês continua
    // valendo e a empresa é ignorada sem quebrar a leitura.
    expect(lerGuardado(JSON.stringify({ empresaId: 7, mes: "2026-08" }))).toEqual({ mes: "2026-08" });
  });

  it("precedência: URL explícita vence o guardado, que vence o padrão", () => {
    const guardado = JSON.stringify({ mes: "2026-08" });
    expect(resolverContexto("?mes=2026-09", guardado)).toEqual({ mes: "2026-09" });
    expect(resolverContexto("", guardado)).toEqual({ mes: "2026-08" });
    expect(resolverContexto("", null)).toEqual({ mes: mesAtual() });
  });
});

describe("ProvedorContexto", () => {
  it("resolve o padrão (mês corrente) sem escrever sozinho na URL", async () => {
    render(
      <ProvedorContexto>
        <Sonda />
      </ProvedorContexto>
    );

    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`pronto|${mesAtual()}|`));
    // Nada de espelhar estado para a barra de endereço: quem escreve é a ação
    // do operador, nunca um efeito de renderização.
    expect(rota.escritas).toEqual([]);
  });

  it("adota a URL explícita ao montar (deep link) e persiste o recorte", async () => {
    rota.busca = "mes=2026-09";
    window.history.replaceState({}, "", `/dashboard/documentos?${rota.busca}`);

    render(
      <ProvedorContexto>
        <Sonda />
      </ProvedorContexto>
    );

    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|2026-09|09/2026"));
    await waitFor(() => expect(window.localStorage.getItem("fluxa:contexto-global") ?? "").toContain("2026-09"));
    expect(rota.aplicadas).toEqual([]);
  });
});

describe("SeletorCompetencia (cabeçalho)", () => {
  it("mostra o mês por extenso, troca a competência e escreve a URL uma vez", async () => {
    const usuario = userEvent.setup();
    render(
      <ProvedorContexto>
        <SeletorCompetencia />
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`pronto|${mesAtual()}`));

    const gatilho = screen.getByRole("button", { name: /competência/i });
    expect(gatilho).toHaveTextContent("outubro/2026");

    await usuario.click(gatilho);
    await usuario.click(screen.getByRole("gridcell", { name: "setembro de 2026" }));

    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|2026-09"));
    expect(rota.escritas).toEqual(["/dashboard/documentos?mes=2026-09"]);
    expect(gatilho).toHaveTextContent("setembro/2026");
    expect(window.localStorage.getItem("fluxa:contexto-global") ?? "").toContain("2026-09");
  });

  it("leva ao mês anterior em um clique, sem sair da tela", async () => {
    const usuario = userEvent.setup();
    render(
      <ProvedorContexto>
        <SeletorCompetencia />
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`pronto|${mesAtual()}`));

    await usuario.click(screen.getByRole("button", { name: /competência/i }));
    await usuario.click(screen.getByRole("button", { name: "Mês anterior" }));

    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`pronto|${mesesAnteriores(mesAtual(), 1)}`));
    expect(rota.escritas).toHaveLength(1);
  });
});

describe("URL com um dono por parâmetro", () => {
  it("filtro de empresa da tela e competência global convivem sem laço", async () => {
    function FiltroDeEmpresa() {
      const { definir } = useUrlEstado();
      return <button onClick={() => definir({ empresa: "42" })}>filtrar empresa 42</button>;
    }

    const usuario = userEvent.setup();
    render(
      <ProvedorContexto>
        <SeletorCompetencia />
        <FiltroDeEmpresa />
        <Sonda />
      </ProvedorContexto>
    );
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent(`pronto|${mesAtual()}|`));

    await usuario.click(screen.getByRole("button", { name: "filtrar empresa 42" }));
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("|42"));

    // A empresa é da tela: o provedor não a apaga nem a ressuscita.
    await new Promise((resolver) => setTimeout(resolver, 20));
    expect(screen.getByTestId("sonda")).toHaveTextContent("|42");
    expect(rota.aplicadas).toEqual(["/dashboard/documentos?empresa=42"]);

    // Trocar a competência depois preserva o filtro da tela.
    await usuario.click(screen.getByRole("button", { name: /competência/i }));
    await usuario.click(screen.getByRole("gridcell", { name: "agosto de 2026" }));
    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("pronto|2026-08|08/2026|42"));
  });

  it("duas escritas no mesmo commit não apagam uma à outra (nem entram em ciclo)", async () => {
    function EscritorDePeriodo() {
      const { definir } = useUrlEstado();
      useEffect(() => {
        definir({ data_inicio: "2026-08-01", data_fim: "2026-08-31" });
      }, [definir]);
      return null;
    }
    function EscritorDeEmpresa() {
      const { definir } = useUrlEstado();
      useEffect(() => {
        definir({ empresa: "7" });
      }, [definir]);
      return null;
    }

    render(
      <ProvedorContexto>
        <EscritorDePeriodo />
        <EscritorDeEmpresa />
        <Sonda />
      </ProvedorContexto>
    );

    await waitFor(() => expect(screen.getByTestId("sonda")).toHaveTextContent("|7"));
    const busca = new URLSearchParams(rota.busca);
    expect(busca.get("data_inicio")).toBe("2026-08-01");
    expect(busca.get("data_fim")).toBe("2026-08-31");
    expect(busca.get("empresa")).toBe("7");

    // Um ciclo A→B→A repetiria alguma URL; nenhuma se repete aqui.
    expect(new Set(rota.aplicadas).size).toBe(rota.aplicadas.length);
    expect(rota.aplicadas.length).toBeLessThanOrEqual(2);
  });
});
