/**
 * O caminho principal não pode obrigar o escritório a entender ou configurar
 * uma estação: pesquisar uma empresa e clicar em "Fazer procuração" abre o
 * portal oficial no computador em uso e deixa o processo pronto para registrar
 * a confirmação humana.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Procuracoes } from "@/app/dashboard/procuracoes/Procuracoes";
import { ProvedorToast } from "@/components/ui/Toast";

const criarJobProcuracao = vi.fn();
const intervencaoJobProcuracao = vi.fn();
const jobProcuracao = vi.fn();
const configuracaoProcuracoes = vi.fn();
const salvarConfiguracaoProcuracoes = vi.fn();

const ROTEIRO = [
  {
    etapa: "acesso_portal",
    fase: "outorga",
    titulo: "Entrar no Portal de Serviços como o cliente",
    instrucao: "Entre com o certificado do cliente.",
    url: "https://servicos.receitafederal.gov.br",
    confirmacao: "Sessão aberta.",
    executor: "operador" as const,
    certificado: "cliente" as const,
  },
];

vi.mock("@/lib/api", () => ({
  api: {
    resumoProcuracoes: vi.fn().mockResolvedValue({
      total_empresas: 1,
      sem_autorizacao: 1,
      em_analise: 0,
      aguardando_aceite: 0,
      ativas: 0,
      expiradas: 0,
      vencendo: 0,
      canceladas: 0,
      jobs_na_fila: 0,
      jobs_aguardando_humano: 0,
      jobs_com_erro: 0,
      jobs_concluidos_24h: 0,
      agentes_online: 0,
      agentes_total: 0,
      agentes_com_assinador: 0,
      certificados_disponiveis: 0,
      certificados_vencendo: 0,
      notificacoes_abertas: 0,
      duracao_media_minutos: 0,
      taxa_sucesso: 0,
    }),
    listarProcuracoes: vi.fn().mockResolvedValue({
      itens: [
        {
          empresa_id: 10,
          razao_social: "Cliente do modo simples LTDA",
          documento: "12345678000195",
          uf: "MG",
          situacao: "sem_autorizacao",
          data_validade: null,
          dias_para_vencer: null,
          prazo_aceite_ate: null,
          dias_para_aceite: null,
          outorgado_documento: "11222333000181",
          protocolo: "",
          origem_dado: "planilha",
          sincronizado_em: null,
          job_id: null,
          job_status: "",
          job_etapa: "",
          job_modo: "assistido",
          job_atualizado_em: null,
          certificado_disponivel: false,
          servicos: 0,
        },
      ],
      total: 1,
      pagina: 1,
      tamanho: 50,
    }),
    notificacoesProcuracao: vi.fn().mockResolvedValue([]),
    configuracaoProcuracoes: (...args: unknown[]) => configuracaoProcuracoes(...args),
    salvarConfiguracaoProcuracoes: (...args: unknown[]) => salvarConfiguracaoProcuracoes(...args),
    roteiroProcuracao: vi.fn().mockResolvedValue({
      passos: [{
        etapa: "acesso_portal",
        fase: "outorga",
        titulo: "Entrar no Portal de Serviços como o cliente",
        instrucao: "Entre com o certificado do cliente.",
        url: "https://servicos.receitafederal.gov.br",
        confirmacao: "Sessão aberta.",
        executor: "operador",
        certificado: "cliente",
      }],
      fundamento: "A confirmação acontece no portal oficial.",
      urls_oficiais: { portal_servicos: "https://servicos.receitafederal.gov.br", ecac: "https://cav.receita.fazenda.gov.br" },
    }),
    criarJobProcuracao: (...args: unknown[]) => criarJobProcuracao(...args),
    intervencaoJobProcuracao: (...args: unknown[]) => intervencaoJobProcuracao(...args),
    jobProcuracao: (...args: unknown[]) => jobProcuracao(...args),
    agentesProcuracao: vi.fn().mockResolvedValue([]),
    processarPendencias: vi.fn(),
    reconhecerNotificacaoProcuracao: vi.fn(),
    registrarOutorga: vi.fn(),
    registrarAceite: vi.fn(),
    retomarJobProcuracao: vi.fn(),
    cancelarJobProcuracao: vi.fn(),
    reprocessarJobProcuracao: vi.fn(),
  },
  urlDaApi: (caminho: string) => caminho,
  ApiError: class extends Error {
    status = 0;
    problemas: unknown[] = [];
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/dashboard/procuracoes",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/shell/ProvedorSessao", () => ({
  useSessao: () => ({ usuario: { id: 1, nome: "Admin" }, somenteLeitura: false, papel: "admin", ehAdmin: true }),
}));

function detalheDoJob() {
  return {
    id: 50,
    status: "intervencao_manual",
    fase: "outorga",
    etapa_atual: "acesso_portal",
    modo: "assistido",
    tentativas: 0,
    codigo_erro: "INTERVENCAO_SOLICITADA",
    classe_erro: "",
    mensagem_erro: "",
    motivo_intervencao: "Operação direta iniciada pelo painel neste computador.",
    criado_em: "2026-09-29T12:00:00Z",
    iniciado_em: null,
    finalizado_em: null,
    agente_id: null,
    vigencia_ate: null,
    protocolo: "",
    empresa_id: 10,
    empresa_nome: "Cliente do modo simples LTDA",
    empresa_documento: "12345678000195",
    escopo_servicos: "ALL",
    servicos: [],
    outorgado_documento: "11222333000181",
    outorgado_nome: "Contabilidade",
    certificado_thumbprint: "",
    proxima_tentativa_em: null,
    eventos: [],
    evidencias: [],
    roteiro: ROTEIRO,
  };
}

function montar() {
  return render(
    <ProvedorToast>
      <Procuracoes />
    </ProvedorToast>
  );
}

describe("modo simples de procurações", () => {
  beforeEach(() => {
    // A tabela virtual mede o painel no navegador; o jsdom não expõe esse
    // observer nativo, então o teste usa uma implementação inerte.
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.clearAllMocks();
    criarJobProcuracao.mockResolvedValue({ id: 50, fase: "outorga" });
    intervencaoJobProcuracao.mockResolvedValue({ id: 50, status: "intervencao_manual" });
    jobProcuracao.mockResolvedValue(detalheDoJob());
    configuracaoProcuracoes.mockResolvedValue({ outorgado_documento: "11222333000181", outorgado_nome: "Contabilidade" });
    salvarConfiguracaoProcuracoes.mockResolvedValue({});
  });

  it("inicia no computador atual sem pedir uma estação e abre somente o portal oficial", async () => {
    const usuario = userEvent.setup();
    const replace = vi.fn();
    const fechar = vi.fn();
    const janela = { opener: window, location: { replace }, close: fechar } as unknown as Window;
    const abrir = vi.spyOn(window, "open").mockReturnValue(janela);

    montar();

    expect(await screen.findByText(/não é necessário configurar estação/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Fazer procuração" }));

    await waitFor(() => expect(criarJobProcuracao).toHaveBeenCalledWith(10));
    expect(intervencaoJobProcuracao).toHaveBeenCalledWith(50, "Operação direta iniciada pelo painel neste computador.");
    expect(abrir).toHaveBeenCalledWith("", "_blank");
    expect(replace).toHaveBeenCalledWith("https://servicos.receitafederal.gov.br");
    expect(fechar).not.toHaveBeenCalled();
    expect(await screen.findByText(/se a Receita pedir CAPTCHA/i)).toBeInTheDocument();

    abrir.mockRestore();
  });

  it("pede só a identidade jurídica do escritório na primeira vez e continua sem tela técnica", async () => {
    const usuario = userEvent.setup();
    const replace = vi.fn();
    const fechar = vi.fn();
    const janela = { opener: window, location: { replace }, close: fechar } as unknown as Window;
    const abrir = vi.spyOn(window, "open").mockReturnValue(janela);
    configuracaoProcuracoes.mockResolvedValue({ outorgado_documento: "", outorgado_nome: "" });

    montar();
    await usuario.click(await screen.findByRole("button", { name: "Fazer procuração" }));

    expect(await screen.findByRole("heading", { name: "Antes de começar" })).toBeInTheDocument();
    expect(screen.getByText(/não é o dado do cliente/i)).toBeInTheDocument();
    expect(criarJobProcuracao).not.toHaveBeenCalled();
    expect(abrir).not.toHaveBeenCalled();

    await usuario.type(screen.getByLabelText(/cnpj\/cpf da sua contabilidade/i), "11222333000181");
    await usuario.type(screen.getByLabelText(/nome da sua contabilidade/i), "Contabilidade Cajuru");
    await usuario.click(screen.getByRole("button", { name: /salvar e começar/i }));

    await waitFor(() =>
      expect(salvarConfiguracaoProcuracoes).toHaveBeenCalledWith(
        expect.objectContaining({
          outorgado_documento: "11222333000181",
          outorgado_nome: "Contabilidade Cajuru",
        })
      )
    );
    await waitFor(() => expect(criarJobProcuracao).toHaveBeenCalledWith(10));
    expect(abrir).toHaveBeenCalledWith("", "_blank");
    expect(replace).toHaveBeenCalledWith("https://servicos.receitafederal.gov.br");
    expect(fechar).not.toHaveBeenCalled();

    abrir.mockRestore();
  });
});
