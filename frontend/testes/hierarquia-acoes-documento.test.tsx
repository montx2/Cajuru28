/**
 * Hierarquia de ação do documento: uma primária, duas secundárias, resto no "⋯".
 *
 * Estes testes existem porque a ficha lateral chegou a ter **três cartões de
 * aviso e seis botões** na mesma coluna, com a MESMA ação escrita de dois
 * jeitos ("Tentar buscar XML completo na SEFAZ" num cartão, "Buscar XML
 * completo na SEFAZ agora" no outro) e aparecendo **duas vezes** na tela de uma
 * nota com erro e mais de 12 dias. O operador não tinha como saber qual botão
 * resolvia o problema dele.
 *
 * O que fica travado aqui:
 *  1. uma ação primária por documento, decidida pelo estado dele;
 *  2. no máximo duas secundárias, e excluir nunca ao lado da primária;
 *  3. um cartão de situação só, com um parágrafo por fato;
 *  4. um rótulo só por ação, em todas as telas;
 *  5. nada é desabilitado sem dizer o porquê.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  acoesDoDocumento,
  idDaAcaoPrimaria,
  ROTULO_ACAO,
  ROTULO_ACAO_LOTE,
  situacaoDoDocumento,
  type DocumentoParaAcoes,
} from "@/lib/acoes-documento";
import { PainelDocumento } from "@/components/fiscal/PainelDocumento";
import { ProvedorToast } from "@/components/ui/Toast";
import type { DocumentoDetalhe } from "@/lib/types";

/* ── fixtures ─────────────────────────────────────────────────────────────── */

const AGORA = Date.now();
const dias = (quantidade: number) => new Date(AGORA - quantidade * 24 * 60 * 60 * 1000).toISOString();

function documento(parcial: Partial<DocumentoParaAcoes>): DocumentoParaAcoes {
  return {
    status: "normal",
    leiaute: "completo",
    data_emissao: dias(2),
    motivo_cancelamento: null,
    cancelado_em: null,
    manifestado_em: null,
    manifestacao_erro: null,
    manifestacao_cstat: null,
    ...parcial,
  };
}

/* ── 1. uma primária, decidida pelo estado ────────────────────────────────── */

describe("a ação primária é uma só e sai do estado do documento", () => {
  it("resumo sem manifestação → Buscar XML completo", () => {
    expect(idDaAcaoPrimaria(documento({ leiaute: "resumo" }))).toBe("buscar-xml-completo");
  });

  it("cStat 596 → Manifestar operação (buscar não resolve mais)", () => {
    const nota = documento({
      leiaute: "resumo",
      manifestacao_cstat: "596",
      manifestacao_erro: "Evento fora do prazo",
    });
    expect(idDaAcaoPrimaria(nota)).toBe("manifestar-operacao");
  });

  it("completo → Baixar XML", () => {
    expect(idDaAcaoPrimaria(documento({ leiaute: "completo" }))).toBe("baixar-xml");
  });

  it("resumo com mais de 12 dias e sem Ciência → Manifestar operação", () => {
    // A Ciência só é aceita até 10 dias da autorização; a folga de 2 existe
    // porque a data de emissão é um piso, não a data da autorização.
    const antiga = documento({ leiaute: "resumo", data_emissao: dias(13) });
    expect(idDaAcaoPrimaria(antiga)).toBe("manifestar-operacao");
    // Dentro do prazo a saída continua sendo buscar.
    const recente = documento({ leiaute: "resumo", data_emissao: dias(5) });
    expect(idDaAcaoPrimaria(recente)).toBe("buscar-xml-completo");
  });

  it("Ciência já registrada tira a nota do caso vencido", () => {
    const antiga = documento({
      leiaute: "resumo",
      data_emissao: dias(30),
      manifestado_em: dias(28),
    });
    expect(idDaAcaoPrimaria(antiga)).toBe("buscar-xml-completo");
  });

  it("devolve sempre exatamente uma primária", () => {
    const casos = [
      documento({}),
      documento({ leiaute: "resumo" }),
      documento({ leiaute: "resumo", manifestacao_cstat: "596" }),
      documento({ leiaute: "metadados" }),
      documento({ status: "cancelada", leiaute: "resumo" }),
    ];
    for (const nota of casos) {
      const { primaria, secundarias, menu } = acoesDoDocumento(nota, { podeExcluir: true });
      expect(primaria).not.toBeNull();
      expect(secundarias.length).toBeLessThanOrEqual(2);
      // excluir nunca é a primária e nunca está ao lado dela
      expect(primaria?.id).not.toBe("excluir-documento");
      expect(secundarias.some((acao) => acao.id === "excluir-documento")).toBe(false);
      expect(menu.some((acao) => acao.id === "excluir-documento")).toBe(true);
    }
  });

  it("não desabilita nada em silêncio", () => {
    const casos = [
      { nota: documento({}), opcoes: { somenteLeitura: true } },
      { nota: documento({ leiaute: "metadados" }), opcoes: {} },
      { nota: documento({ leiaute: "completo", xml_disponivel: false }), opcoes: {} },
      { nota: documento({ status: "cancelada", leiaute: "resumo" }), opcoes: { podeExcluir: true } },
    ];
    for (const { nota, opcoes } of casos) {
      const { primaria, secundarias, menu } = acoesDoDocumento(nota, opcoes);
      for (const acao of [primaria, ...secundarias, ...menu]) {
        if (acao?.desabilitado) expect(acao.motivo).toBeTruthy();
      }
    }
  });
});

/* ── 3. um cartão de situação, não três ───────────────────────────────────── */

describe("a situação vira um bloco só, com um parágrafo por fato", () => {
  it("596 + resumo são dois parágrafos de UM bloco", () => {
    const situacao = situacaoDoDocumento(
      documento({
        leiaute: "resumo",
        manifestacao_cstat: "596",
        manifestacao_erro: "Evento fora do prazo",
        data_emissao: dias(20),
      })
    );
    expect(situacao).not.toBeNull();
    // tom do fato mais grave: 596 é erro, resumo é espera
    expect(situacao?.tom).toBe("erro");
    // os dois fatos estão no mesmo bloco
    expect(situacao?.paragrafos.length).toBeGreaterThanOrEqual(3);
    expect(situacao?.paragrafos.join(" ")).toMatch(/cStat 596/);
    expect(situacao?.paragrafos.join(" ")).toMatch(/resumo/i);
    // e a ação citada é a da primária — nunca um terceiro nome
    expect(situacao?.acao).toBe(ROTULO_ACAO["manifestar-operacao"]);
    expect(situacao?.acao).toBe(
      ROTULO_ACAO[idDaAcaoPrimaria(documento({ leiaute: "resumo", manifestacao_cstat: "596" }))]
    );
  });

  it("cancelamento entra no mesmo bloco, sem cartão próprio", () => {
    const situacao = situacaoDoDocumento(
      documento({
        status: "cancelada",
        motivo_cancelamento: "Duplicidade",
        leiaute: "resumo",
      })
    );
    expect(situacao?.titulo).toMatch(/cancelada/i);
    expect(situacao?.paragrafos.join(" ")).toMatch(/Duplicidade/);
    expect(situacao?.paragrafos.join(" ")).toMatch(/resumo/i);
  });

  it("documento saudável não ganha cartão", () => {
    expect(situacaoDoDocumento(documento({}))).toBeNull();
  });

  it("XML sumiu do disco é dito na ficha, como é dito na pendencias.csv", () => {
    const situacao = situacaoDoDocumento(documento({ xml_disponivel: false }));
    expect(situacao?.titulo).toMatch(/não está no disco/i);
    const { primaria } = acoesDoDocumento(documento({ xml_disponivel: false }));
    expect(primaria?.desabilitado).toBe(true);
    expect(primaria?.motivo).toMatch(/Capture novamente pela SEFAZ/);
  });
});

/* ── 1 e 2 na tela: a ficha renderizada ───────────────────────────────────── */

const detalheDocumento = vi.fn();
const completarXmlDocumento = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    detalheDocumento: (...args: unknown[]) => detalheDocumento(...args),
    completarXmlDocumento: (...args: unknown[]) => completarXmlDocumento(...args),
    baixarXmlDocumento: vi.fn(),
    obterXmlTexto: vi.fn(),
    manifestarConclusiva: vi.fn(),
  },
}));

function detalhe(parcial: Partial<DocumentoDetalhe>): DocumentoDetalhe {
  return {
    id: 7,
    empresa_id: 3,
    tipo: "nfe",
    direcao: "tomada",
    chave_acesso: "31260907485646000155550010000602201187626989",
    data_emissao: dias(20),
    valor_total: 2261.84,
    status: "normal",
    leiaute: "resumo",
    empresa_razao_social: "ARM LOGISTICA",
    empresa_cnpj: "12345678000199",
    empresa_uf: "MG",
    importado_em: dias(20),
    xml_disponivel: true,
    xml_bytes: 900,
    execucao_id: 1,
    ...parcial,
  } as DocumentoDetalhe;
}

async function abrirFicha(nota: Partial<DocumentoDetalhe>) {
  detalheDocumento.mockResolvedValue(detalhe(nota));
  const resultado = render(
    <ProvedorToast>
      <PainelDocumento documentoId={7} aoFechar={() => {}} aoExcluir={() => {}} />
    </ProvedorToast>
  );
  // O painel é um portal para `document.body`: consultar `container` não acha
  // nada. `baseElement` é o documento inteiro.
  await waitFor(() =>
    expect(resultado.baseElement.querySelectorAll("[data-acao='primaria']").length).toBeGreaterThan(0)
  );
  return resultado.baseElement;
}

describe("a ficha renderizada", () => {
  beforeEach(() => {
    detalheDocumento.mockReset();
    completarXmlDocumento.mockReset();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      }
    );
  });

  it("mostra no máximo uma ação primária e até duas secundárias", async () => {
    const ficha = await abrirFicha({
      leiaute: "resumo",
      manifestacao_cstat: "596",
      manifestacao_erro: "Evento fora do prazo",
    });

    expect(ficha.querySelectorAll("[data-acao='primaria']")).toHaveLength(1);
    expect(ficha.querySelectorAll("[data-acao='secundaria']").length).toBeLessThanOrEqual(2);
  });

  it("596 com nota velha: uma ação só, e é Manifestar operação", async () => {
    // Este é exatamente o caso que aparecia DUAS vezes na mesma tela antes.
    const ficha = await abrirFicha({
      leiaute: "resumo",
      manifestacao_cstat: "596",
      manifestacao_erro: "Evento fora do prazo",
      data_emissao: dias(20),
    });

    const botoes = Array.from(ficha.querySelectorAll("button"));
    const manifestar = botoes.filter((botao) =>
      /manifestar operação/i.test(botao.textContent ?? "")
    );
    expect(manifestar).toHaveLength(1);
    // e a busca, que não resolve este caso, não aparece como ação
    expect(
      botoes.filter((botao) => /buscar xml completo/i.test(botao.textContent ?? ""))
    ).toHaveLength(0);
    // um cartão de situação só
    expect(ficha.querySelectorAll("[data-situacao='documento']")).toHaveLength(1);
  });

  it("resumo recente: a primária é Buscar XML completo", async () => {
    await abrirFicha({ leiaute: "resumo", data_emissao: dias(2) });
    expect(screen.getByRole("button", { name: /buscar xml completo/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /manifestar operação/i })).toBeNull();
  });

  it("excluir documento não fica ao lado do botão principal — só no menu", async () => {
    const usuario = userEvent.setup();
    await abrirFicha({ leiaute: "completo" });

    // fechada, a exclusão não está na tela
    expect(screen.queryByText("Excluir documento")).toBeNull();

    await usuario.click(screen.getByRole("button", { name: /mais ações do documento/i }));
    expect(await screen.findByRole("menuitem", { name: /excluir documento/i })).toBeTruthy();
  });

  it("completo: a primária volta a ser Baixar XML", async () => {
    const ficha = await abrirFicha({ leiaute: "completo" });
    const primarias = ficha.querySelectorAll("[data-acao='primaria'] button");
    expect(primarias).toHaveLength(1);
    expect(primarias[0]?.textContent).toMatch(/baixar xml/i);
  });

  afterEach(() => vi.unstubAllGlobals());
});

/* ── 4. um rótulo só por ação, em todas as telas ──────────────────────────── */

function arquivosTs(caminho: string): string[] {
  const absoluto = resolve(caminho);
  const achados: string[] = [];
  for (const entrada of readdirSync(absoluto)) {
    const completo = resolve(absoluto, entrada);
    if (statSync(completo).isDirectory()) achados.push(...arquivosTs(completo));
    else if (/\.(ts|tsx)$/.test(entrada)) achados.push(completo);
  }
  return achados;
}

describe("um rótulo por ação", () => {
  it("os rótulos antigos da mesma ação não voltam em tela nenhuma", () => {
    const raiz = process.cwd().endsWith("frontend") ? process.cwd() : resolve(process.cwd(), "frontend");
    const fontes = [...arquivosTs(resolve(raiz, "app")), ...arquivosTs(resolve(raiz, "components"))];
    expect(fontes.length).toBeGreaterThan(10);

    // Formas que a MESMA ação já teve. Se alguma voltar, a regra quebrou.
    const proibidos = [
      "Tentar buscar XML completo na SEFAZ",
      "Buscar XML completo na SEFAZ agora",
      "Completar XMLs",
      "Completar XML pela chave",
      '"Resolver"',
    ];
    for (const arquivo of fontes) {
      const codigo = readFileSync(arquivo, "utf8");
      for (const rotulo of proibidos) {
        expect(codigo, `${arquivo} ainda usa "${rotulo}"`).not.toContain(rotulo);
      }
    }
  });

  it("o lote usa o mesmo verbo do singular", () => {
    expect(ROTULO_ACAO["buscar-xml-completo"]).toBe("Buscar XML completo");
    expect(ROTULO_ACAO_LOTE.buscarXml).toBe("Buscar todos os XMLs");
    expect(ROTULO_ACAO_LOTE.manifestar(3)).toBe("Manifestar as 3 notas");
    expect(ROTULO_ACAO["manifestar-operacao"]).toBe("Manifestar operação");
  });
});
