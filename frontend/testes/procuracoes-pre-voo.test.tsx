/**
 * O pré-voo existe para uma coisa: o operador saber, antes de abrir o portal,
 * quem dá para tocar hoje. Os testes cobrem as três decisões que essa tela
 * toma e que são fáceis de quebrar sem ninguém perceber:
 *
 *  1. bloqueio de ambiente é urgente e vem antes da lista (não adianta olhar
 *     cliente por cliente se o outorgado nem está configurado);
 *  2. "dispensado" — quem já tem autorização ativa — não é pendência e sai da
 *     tela por padrão, senão a fila de trabalho nasce inflada;
 *  3. o CSV vai por fetch autenticado, não por link direto.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PreVoo } from "@/app/dashboard/procuracoes/pre-voo/PreVoo";
import { ProvedorToast } from "@/components/ui/Toast";
import type { RelatorioPrevoo } from "@/lib/types";

const preVooProcuracoes = vi.fn();
const metricasProcuracoes = vi.fn();
const baixarRelatorioProcuracoes = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    preVooProcuracoes: (...args: unknown[]) => preVooProcuracoes(...args),
    metricasProcuracoes: (...args: unknown[]) => metricasProcuracoes(...args),
    baixarRelatorioProcuracoes: (...args: unknown[]) => baixarRelatorioProcuracoes(...args),
  },
}));

const SEM_METRICA = {
  jobs_considerados: 0,
  concluidos: 0,
  falhados: 0,
  cancelados: 0,
  taxa_sucesso: 0,
  duracao_media_minutos: 0,
  espera_humana_media_minutos: 0,
  processamento_medio_minutos: 0,
  tempo_por_etapa: {},
  erros_por_codigo: {},
  erros_por_classe: {},
  total_retentativas: 0,
  intervencoes_humanas: 0,
  clientes_por_hora: 0,
};

function relatorio(parcial: Partial<RelatorioPrevoo> = {}): RelatorioPrevoo {
  return {
    gerado_em: "2026-09-29T12:00:00+00:00",
    pode_iniciar: true,
    bloqueio_de_ambiente: false,
    ambiente: [],
    contagem: { apto: 0, atencao: 0, bloqueado: 0, dispensado: 0 },
    por_codigo: {},
    linhas: [],
    ...parcial,
  };
}

function renderizar() {
  return render(
    <ProvedorToast>
      <PreVoo />
    </ProvedorToast>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  metricasProcuracoes.mockResolvedValue(SEM_METRICA);
});

describe("pré-voo do lote", () => {
  it("bloqueio de ambiente aparece como alerta urgente com a ação de correção", async () => {
    preVooProcuracoes.mockResolvedValue(
      relatorio({
        pode_iniciar: false,
        bloqueio_de_ambiente: true,
        ambiente: [
          {
            codigo: "OUTORGADO_AUSENTE",
            nivel: "bloqueado",
            mensagem: "Outorgado não configurado",
            acao: "Preencha o CNPJ da contabilidade em Configurar.",
          },
        ],
      })
    );

    renderizar();

    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Outorgado não configurado");
    expect(alerta).toHaveTextContent("Preencha o CNPJ da contabilidade");
  });

  it("não confunde bloqueio do ambiente com carteira sem pendências", async () => {
    preVooProcuracoes.mockResolvedValue(
      relatorio({
        pode_iniciar: false,
        bloqueio_de_ambiente: true,
        ambiente: [
          {
            codigo: "OUTORGADO_AUSENTE",
            nivel: "bloqueado",
            mensagem: "Outorgado não configurado",
            acao: "Configure o outorgado antes de avaliar a carteira.",
          },
        ],
      })
    );

    renderizar();

    expect(await screen.findByText("Carteira não avaliada")).toBeInTheDocument();
    expect(screen.getByText(/Resolva os bloqueios de ambiente acima/)).toBeInTheDocument();
    expect(screen.queryByText("Todos os clientes avaliados já têm autorização ativa.")).not.toBeInTheDocument();
  });

  it("quem já está autorizado fica fora da lista até o operador pedir", async () => {
    preVooProcuracoes.mockResolvedValue(
      relatorio({
        contagem: { apto: 1, atencao: 0, bloqueado: 0, dispensado: 1 },
        linhas: [
          {
            empresa_id: 1,
            razao_social: "CLIENTE PENDENTE LTDA",
            documento: "12.***.***/0001-95",
            situacao: "apto",
            certificado: "TITULAR A",
            certificado_valido_ate: "2027-01-10T00:00:00+00:00",
            vigencia_prevista: "2031-09-29T00:00:00+00:00",
            achados: [],
          },
          {
            empresa_id: 2,
            razao_social: "CLIENTE RESOLVIDO LTDA",
            documento: "98.***.***/0001-10",
            situacao: "dispensado",
            certificado: "",
            certificado_valido_ate: null,
            vigencia_prevista: null,
            achados: [
              {
                codigo: "AUTORIZACAO_JA_EXISTE",
                nivel: "dispensado",
                mensagem: "Autorização ativa até 2029-03-01",
                acao: "Nada a fazer.",
              },
            ],
          },
        ],
      })
    );

    renderizar();

    expect(await screen.findByText("CLIENTE PENDENTE LTDA")).toBeInTheDocument();
    expect(screen.queryByText("CLIENTE RESOLVIDO LTDA")).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText(/Ocultar quem já está autorizado/i));
    expect(await screen.findByText("CLIENTE RESOLVIDO LTDA")).toBeInTheDocument();
  });

  it("bloqueados vêm primeiro: a tela é uma lista de trabalho, não um cadastro", async () => {
    preVooProcuracoes.mockResolvedValue(
      relatorio({
        contagem: { apto: 1, atencao: 1, bloqueado: 1, dispensado: 0 },
        linhas: [
          {
            empresa_id: 1,
            razao_social: "ZZZ APTO LTDA",
            documento: "11.***.***/0001-11",
            situacao: "apto",
            certificado: "TITULAR A",
            certificado_valido_ate: null,
            vigencia_prevista: null,
            achados: [],
          },
          {
            empresa_id: 2,
            razao_social: "AAA BLOQUEADO LTDA",
            documento: "22.***.***/0001-22",
            situacao: "bloqueado",
            certificado: "",
            certificado_valido_ate: null,
            vigencia_prevista: null,
            achados: [
              {
                codigo: "CERTIFICADO_NAO_ENCONTRADO",
                nivel: "bloqueado",
                mensagem: "Sem certificado A1 na estação",
                acao: "Importe o certificado do cliente.",
              },
            ],
          },
          {
            empresa_id: 3,
            razao_social: "MMM ATENCAO LTDA",
            documento: "33.***.***/0001-33",
            situacao: "atencao",
            certificado: "TITULAR C",
            certificado_valido_ate: null,
            vigencia_prevista: null,
            achados: [],
          },
        ],
      })
    );

    renderizar();

    await screen.findByText("AAA BLOQUEADO LTDA");
    const nomes = screen.getAllByText(/LTDA$/).map((elemento) => elemento.textContent);
    expect(nomes).toEqual(["AAA BLOQUEADO LTDA", "MMM ATENCAO LTDA", "ZZZ APTO LTDA"]);
  });

  it("o CSV respeita o filtro da tela e é baixado autenticado", async () => {
    preVooProcuracoes.mockResolvedValue(relatorio());
    baixarRelatorioProcuracoes.mockResolvedValue(undefined);

    renderizar();
    await screen.findByRole("button", { name: /Baixar CSV/i });

    await userEvent.click(screen.getByRole("button", { name: /Baixar CSV/i }));
    await waitFor(() => expect(baixarRelatorioProcuracoes).toHaveBeenCalledWith({ somentePendentes: true }));

    await userEvent.click(screen.getByLabelText(/Ocultar quem já está autorizado/i));
    await userEvent.click(screen.getByRole("button", { name: /Baixar CSV/i }));
    await waitFor(() => expect(baixarRelatorioProcuracoes).toHaveBeenLastCalledWith({ somentePendentes: false }));
  });
});
