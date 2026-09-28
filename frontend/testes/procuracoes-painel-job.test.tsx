/**
 * Painel do processo: a trilha de auditoria é o que o operador usa para
 * confiar (ou não) no andamento — e o defeito real era ela falar em código:
 * "— → intervencao_manual (PORTAL_DESAFIO_ADICIONAL) · sistema" não diz nem
 * o que aconteceu, nem quem fez, nem o que fazer agora.
 *
 * Aqui se verifica a tradução: rótulo de estado em português, frase do
 * catálogo de erros, ator com nome ("você" quando é a própria sessão) e o
 * aviso honesto quando o processo espera uma estação que não existe.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PainelJob } from "@/app/dashboard/procuracoes/PainelJob";
import { ProvedorToast } from "@/components/ui/Toast";
import type { EventoJobProcuracao, JobProcuracaoDetalhe } from "@/lib/types";

const jobProcuracao = vi.fn();
const agentesProcuracao = vi.fn();
const registrarOutorga = vi.fn();
const intervencaoJobProcuracao = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    jobProcuracao: (...args: unknown[]) => jobProcuracao(...args),
    agentesProcuracao: (...args: unknown[]) => agentesProcuracao(...args),
    registrarOutorga: (...args: unknown[]) => registrarOutorga(...args),
    registrarAceite: vi.fn(),
    retomarJobProcuracao: vi.fn(),
    intervencaoJobProcuracao: (...args: unknown[]) => intervencaoJobProcuracao(...args),
    cancelarJobProcuracao: vi.fn(),
    reprocessarJobProcuracao: vi.fn(),
  },
  urlDaApi: (caminho: string) => caminho,
  ApiError: class extends Error {
    status = 0;
    problemas: unknown[] = [];
  },
}));

let idDoUsuarioLogado = 1;

vi.mock("@/components/shell/ProvedorSessao", () => ({
  useSessao: () => ({
    usuario: { id: idDoUsuarioLogado, nome: "Admin", papel: "admin" },
    somenteLeitura: false,
    papel: "admin",
    ehAdmin: true,
  }),
}));

const SEM_ESTACAO = { situacao: "revogado", ativo: false };

function evento(parcial: Partial<EventoJobProcuracao>): EventoJobProcuracao {
  return {
    id: 1,
    job_id: 7,
    quando: "2026-09-20T14:03:00",
    tipo: "transicao",
    etapa: "",
    status_anterior: "",
    status_novo: "",
    mensagem: "",
    codigo_erro: "",
    ator: "sistema",
    ator_rotulo: "Sistema",
    usuario_id: null,
    ...parcial,
  };
}

function job(parcial: Partial<JobProcuracaoDetalhe>): JobProcuracaoDetalhe {
  return {
    id: 7,
    status: "aguardando_agente",
    fase: "outorga",
    etapa_atual: "",
    modo: "assistido",
    tentativas: 0,
    codigo_erro: "",
    classe_erro: "",
    mensagem_erro: "",
    motivo_intervencao: "",
    criado_em: "2026-09-20T14:00:00",
    iniciado_em: null,
    finalizado_em: null,
    agente_id: null,
    vigencia_ate: null,
    protocolo: "",
    empresa_id: 3,
    empresa_nome: "R10 NOGUEIRA SAUDE LTDA",
    empresa_documento: "42694635000186",
    escopo_servicos: "ALL",
    servicos: [],
    outorgado_documento: "11222333000181",
    outorgado_nome: "CONTABILIDADE CAJURU LTDA",
    certificado_thumbprint: "",
    proxima_tentativa_em: null,
    eventos: [],
    evidencias: [],
    roteiro: [],
    ...parcial,
  };
}

function montar() {
  return render(
    <ProvedorToast>
      <PainelJob jobId={7} aoFechar={() => {}} aoMudar={() => {}} />
    </ProvedorToast>
  );
}

describe("painel do processo de autorização", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    idDoUsuarioLogado = 1;
    agentesProcuracao.mockResolvedValue([]);
    registrarOutorga.mockResolvedValue({});
    intervencaoJobProcuracao.mockResolvedValue({});
  });

  it("traduz a trilha: rótulo de estado, frase do catálogo e ator com nome", async () => {
    jobProcuracao.mockResolvedValue(
      job({
        status: "intervencao_manual",
        eventos: [
          evento({
            id: 1,
            status_novo: "aguardando_agente",
            mensagem: "Aguardando estação disponível.",
          }),
          evento({
            id: 2,
            status_anterior: "aguardando_agente",
            status_novo: "intervencao_manual",
            tipo: "intervencao_forcada",
            codigo_erro: "INTERVENCAO_SOLICITADA",
            mensagem: "Intervenção solicitada: assumido pelo operador.",
            ator: "operador:1",
            ator_rotulo: "Admin",
            usuario_id: 1,
          }),
        ],
      })
    );

    montar();

    const tituloTrilha = await screen.findByText("Trilha do processo");
    const trilha = tituloTrilha.closest("section") as HTMLElement;

    // Rótulos de estado, não os códigos crus.
    expect(within(trilha).getAllByText("Aguardando estação").length).toBeGreaterThan(0);
    expect(within(trilha).getAllByText("Precisa de você").length).toBeGreaterThan(0);
    // O travessão morto "— →" foi substituído pela primeira transição sem origem.
    expect(within(trilha).queryByText(/^—/)).toBeNull();
    // A frase do catálogo aparece junto do código (que continua como referência).
    expect(
      within(trilha).getByText(/Intervenção pedida por uma pessoa do escritório/i)
    ).toBeInTheDocument();
    expect(within(trilha).getByText(/\(INTERVENCAO_SOLICITADA\)/)).toBeInTheDocument();
    // Quem fez foi a própria sessão: "você", não "operador:1".
    expect(within(trilha).getAllByText(/você/i).length).toBeGreaterThan(0);
    expect(within(trilha).queryByText(/operador:1/)).toBeNull();
  });

  it("mostra o nome do colega quando quem agiu foi outra pessoa", async () => {
    idDoUsuarioLogado = 2;
    jobProcuracao.mockResolvedValue(
      job({
        eventos: [
          evento({
            id: 3,
            status_novo: "intervencao_manual",
            ator: "operador:1",
            ator_rotulo: "Ana",
            usuario_id: 1,
          }),
        ],
      })
    );

    montar();
    const trilha = await screen.findByText("Trilha do processo");
    const secao = trilha.closest("section") as HTMLElement;
    expect(await within(secao).findByText(/Ana/)).toBeInTheDocument();
    // O rodapé do evento é "<quando> · <ator>": ato de outra pessoa nunca é
    // assinado como "você" (o rótulo de estado "Precisa de você" não conta).
    expect(secao.textContent).toContain("· Ana");
    expect(secao.textContent).not.toContain("· você");
  });

  it("avisa quando o processo espera uma estação e nenhuma está de pé", async () => {
    jobProcuracao.mockResolvedValue(job({ status: "aguardando_agente" }));
    agentesProcuracao.mockResolvedValue([SEM_ESTACAO]);

    montar();

    expect(await screen.findByText(/nenhuma está de pé/i)).toBeInTheDocument();
    expect(screen.getByText(/instalar o agent/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /estações/i })).toHaveAttribute(
      "href",
      "/dashboard/procuracoes/estacoes"
    );
    expect(screen.getByText(/fazer a outorga direto no portal da Receita/i)).toBeInTheDocument();
  });

  it("não acusa falta de estação quando há uma viva", async () => {
    jobProcuracao.mockResolvedValue(job({ status: "aguardando_agente" }));
    agentesProcuracao.mockResolvedValue([
      { situacao: "online", ativo: true },
      SEM_ESTACAO,
    ]);

    montar();
    await screen.findByText("R10 NOGUEIRA SAUDE LTDA");
    expect(screen.queryByText(/nenhuma está de pé/i)).toBeNull();
  });

  it("libera o registro manual de outorga a partir da intervenção", async () => {
    const usuario = userEvent.setup();
    jobProcuracao.mockResolvedValue(
      job({
        status: "intervencao_manual",
        eventos: [],
      })
    );

    montar();

    await usuario.type(await screen.findByLabelText(/^protocolo$/i), "2026.000123456");
    await usuario.type(
      screen.getByLabelText(/texto de confirmação do portal/i),
      "Autorização registrada. Situação: Em Análise."
    );
    await usuario.click(screen.getByRole("button", { name: /registrar outorga/i }));

    await waitFor(() =>
      expect(registrarOutorga).toHaveBeenCalledWith(7, {
        protocolo: "2026.000123456",
        confirmacao_portal: "Autorização registrada. Situação: Em Análise.",
      })
    );
  });

  it("explica em português o código do erro que travou o processo", async () => {
    jobProcuracao.mockResolvedValue(
      job({
        status: "intervencao_manual",
        codigo_erro: "PORTAL_DESAFIO_ADICIONAL",
        mensagem_erro: "Desafio adicional de segurança no portal.",
      })
    );

    montar();

    expect(
      await screen.findByText(/A Receita apresentou um desafio adicional de segurança/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/código: PORTAL_DESAFIO_ADICIONAL/i)).toBeInTheDocument();
  });
});
