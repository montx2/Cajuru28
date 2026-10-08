/**
 * O aviso de captura na lista do acervo.
 *
 * A importação demora (consulta por NSU na SEFAZ) e a lista mostra o que já
 * chegou. Sem dizer isso, o operador olha a lista parada e conclui que o
 * sistema pegou tudo — ou que não veio nada. Cada teste aqui é um dos desfechos
 * que a tela precisa saber contar.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CapturaEmAndamento, JANELA_DESFECHO_MS } from "@/components/fiscal/CapturaEmAndamento";
import type { CapturaAoVivo, ExecucaoAoVivo, ExecucaoImportacao } from "@/lib/types";

function rodada(extra: Partial<ExecucaoAoVivo> = {}): ExecucaoAoVivo {
  return {
    execucao_id: 1,
    empresa_id: 7,
    razao_social: "Alfa Ltda",
    tipo: "nfe",
    status: "em_andamento",
    documentos_importados: 0,
    ultimo_nsu: null,
    iniciado_em: new Date().toISOString(),
    aguardando_ate: null,
    motivo_espera: null,
    aviso: null,
    mensagem_erro: null,
    ...extra,
  };
}

function captura(extra: Partial<CapturaAoVivo> = {}): CapturaAoVivo {
  return { em_andamento: [], documentos_em_andamento: 0, fora_do_recorte: 0, ultima: null, ...extra };
}

function concluida(extra: Partial<ExecucaoImportacao> = {}): ExecucaoImportacao {
  return {
    id: 9,
    empresa_id: 7,
    empresa_razao_social: "Alfa Ltda",
    tipo: "nfe",
    status: "concluida",
    documentos_importados: 0,
    documentos_cancelados: 0,
    eventos_nao_reconhecidos: 0,
    documentos_no_periodo: 0,
    documentos_fora_do_periodo: 0,
    iniciado_em: new Date(Date.now() - 60_000).toISOString(),
    finalizado_em: new Date().toISOString(),
    mensagem_erro: null,
    falha: null,
    aviso: null,
    ultimo_nsu: null,
    data_inicio: null,
    data_fim: null,
    tentativas: 0,
    bloqueado_ate: null,
    origem: "manual",
    forcar: false,
    ...extra,
  };
}

describe("enquanto a captura roda", () => {
  it("diz que está capturando, quantos documentos já entraram e que a lista se completa sozinha", () => {
    render(
      <CapturaEmAndamento
        captura={captura({
          em_andamento: [rodada({ documentos_importados: 12 })],
          documentos_em_andamento: 12,
        })}
        aoAtualizar={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveAttribute("data-captura", "em-andamento");
    expect(screen.getByText(/12 documentos já entraram nesta captura/)).toBeInTheDocument();
    expect(screen.getByText(/se atualiza sozinha/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /atualizar agora/i })).toBeInTheDocument();
  });

  it("sem documento novo ainda, não deixa a dúvida no ar", () => {
    render(<CapturaEmAndamento captura={captura({ em_andamento: [rodada()] })} aoAtualizar={vi.fn()} />);

    expect(screen.getByText(/Nenhum documento novo ainda nesta captura/)).toBeInTheDocument();
  });

  it("explica a espera pela janela da SEFAZ em vez de parecer travado", () => {
    render(
      <CapturaEmAndamento
        captura={captura({
          em_andamento: [
            rodada({
              status: "aguardando",
              aguardando_ate: new Date(Date.now() + 40 * 60_000).toISOString(),
            }),
          ],
        })}
        aoAtualizar={vi.fn()}
      />,
    );

    expect(screen.getByText(/janela de consumo da SEFAZ/)).toBeInTheDocument();
    expect(screen.getByText(/volta em 40 min/)).toBeInTheDocument();
    expect(screen.getByText(/Captura aguardando a SEFAZ/)).toBeInTheDocument();
  });

  it("o botão de atualizar agora recarrega o recorte", async () => {
    const usuario = userEvent.setup();
    const aoAtualizar = vi.fn();
    render(
      <CapturaEmAndamento
        captura={captura({ em_andamento: [rodada()], documentos_em_andamento: 1 })}
        aoAtualizar={aoAtualizar}
      />,
    );

    await usuario.click(screen.getByRole("button", { name: /atualizar agora/i }));
    expect(aoAtualizar).toHaveBeenCalledOnce();
  });
});

describe("quando a captura é de outra empresa", () => {
  it("avisa sem fingir que a lista deste recorte vai mudar", () => {
    render(<CapturaEmAndamento captura={captura({ fora_do_recorte: 2 })} aoAtualizar={vi.fn()} />);

    expect(screen.getByText(/2 capturas estão rodando em outras empresas/)).toBeInTheDocument();
    expect(screen.getByText(/Este recorte não muda por causa delas/)).toBeInTheDocument();
  });
});

describe("o desfecho da última captura", () => {
  it("mostra quantos documentos novos entraram", () => {
    render(
      <CapturaEmAndamento
        captura={captura({ ultima: concluida({ documentos_importados: 4 }) })}
        aoAtualizar={vi.fn()}
      />,
    );

    expect(screen.getByText("Captura concluída")).toBeInTheDocument();
    expect(screen.getByText(/4 documentos novos entraram em Alfa Ltda/)).toBeInTheDocument();
  });

  it("responde 'não veio nenhum' — e explica quando o que veio caiu fora do período", () => {
    render(
      <CapturaEmAndamento
        captura={captura({ ultima: concluida({ documentos_importados: 0, documentos_fora_do_periodo: 3 }) })}
        aoAtualizar={vi.fn()}
      />,
    );

    expect(screen.getByText(/não trouxe documento novo/)).toBeInTheDocument();
    expect(screen.getByText(/3 documento\(s\) chegaram fora do período/)).toBeInTheDocument();
  });

  it("falha aparece como falha, com o motivo e sem drama", () => {
    render(
      <CapturaEmAndamento
        captura={captura({
          ultima: concluida({ status: "erro", mensagem_erro: "Certificado A1 vencido." }),
        })}
        aoAtualizar={vi.fn()}
      />,
    );

    expect(screen.getByText("A captura terminou com erro")).toBeInTheDocument();
    expect(screen.getByText(/Certificado A1 vencido/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ver o que aconteceu/i })).toBeInTheDocument();
  });

  it("não repete um desfecho velho — passada a janela, some", () => {
    const velho = new Date(Date.now() - JANELA_DESFECHO_MS - 60_000).toISOString();
    const { container } = render(
      <CapturaEmAndamento
        captura={captura({ ultima: concluida({ documentos_importados: 4, finalizado_em: velho }) })}
        aoAtualizar={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("fechar tira o desfecho da tela até a próxima captura terminar", async () => {
    const usuario = userEvent.setup();
    const { rerender, container } = render(
      <CapturaEmAndamento
        captura={captura({ ultima: concluida({ documentos_importados: 4 }) })}
        aoAtualizar={vi.fn()}
      />,
    );

    await usuario.click(screen.getByRole("button", { name: /fechar aviso/i }));
    expect(container).toBeEmptyDOMElement();

    // Uma captura NOVA terminando volta a avisar (o desfecho anterior não vale mais).
    rerender(
      <CapturaEmAndamento
        captura={captura({ ultima: concluida({ id: 10, documentos_importados: 2 }) })}
        aoAtualizar={vi.fn()}
      />,
    );
    expect(screen.getByText("Captura concluída")).toBeInTheDocument();
  });
});

/**
 * A ligação da tela: o aviso sozinho não basta — ele precisa estar ligado na
 * lista, no recorte certo, e o laço de recarga não pode rodar a lista quando
 * não há captura (senão a tela de documentos fica consultando a API à toa).
 */
describe("a tela de documentos liga o aviso do jeito certo", () => {
  const fonteDaTela = readFileSync(resolve(__dirname, "..", "app/dashboard/documentos/Documentos.tsx"), "utf8");

  it("renderiza o aviso com o recorte da tela", () => {
    expect(fonteDaTela).toContain("<CapturaEmAndamento");
    expect(fonteDaTela).toContain("escopo={empresaSelecionada?.razao_social ?? null}");
    expect(fonteDaTela).toMatch(/api\.capturaAoVivo\(empresa \? \[empresa\] : undefined\)/);
  });

  it("só recarrega a lista em laço enquanto há captura — e só com o período escolhido", () => {
    expect(fonteDaTela).toContain("usePolling(recarregarDoRecorte, capturando && pronto ? 5_000 : null)");
    expect(fonteDaTela).toContain("usePolling(captura.atualizar, capturando ? 5_000 : 20_000)");
  });

  it("o título da aba avisa quem está em outra aba do navegador", () => {
    expect(fonteDaTela).toContain('"Capturando documentos · Fluxa"');
  });

  it("recarrega uma última vez quando a captura termina", () => {
    // O laço de 5 s para no mesmo instante em que a rodada fecha: sem a
    // recarga final, o último lote que chegou ficaria de fora da lista
    // exatamente quando o operador olha para conferir.
    expect(fonteDaTela).toContain("estavaCapturando.current");
    expect(fonteDaTela).toContain("estavaCapturando.current = true");
  });
});

/**
 * O disparo termina na tela de Importações — e antes ficava por isso mesmo:
 * "Fechar" e nada mais. Quem disparou tinha que adivinhar onde os documentos
 * aparecem, que é justamente onde a dúvida "veio ou não veio?" nasce.
 */
describe("o disparo diz para onde olhar", () => {
  const fonteDoDisparo = readFileSync(resolve(__dirname, "..", "app/dashboard/importacoes/Importacoes.tsx"), "utf8");

  it("o resultado aponta Documentos e a central de execuções", () => {
    expect(fonteDoDisparo).toContain('href="/dashboard/documentos"');
    expect(fonteDoDisparo).toContain('href="/dashboard/execucoes?aba=fila"');
    expect(fonteDoDisparo).toMatch(/entram na lista conforme chegam/);
  });

  it("só aparece depois de disparar de verdade (na prévia quem decide é o botão)", () => {
    expect(fonteDoDisparo).toContain('resultado.modo === "resultado" && resultado.dados.enfileiradas > 0');
  });
});
