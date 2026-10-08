/**
 * Desfecho de execução (Bloco C da auditoria, C2).
 *
 * O que a auditoria pegou: uma execução com `status: "erro"` e
 * `finalizado_em: null` era desenhada como trabalho vivo — coluna "Duração"
 * com "em curso" e linha do tempo crescendo a cada segundo. Quem olhava a
 * central via uma falha de dias atrás parecendo varredura em andamento, e a
 * pergunta "terminou?" ficava sem resposta na própria tela.
 *
 * O defeito real tem duas metades, e as duas estão travadas aqui:
 *  1. quem encerra a execução precisa gravar o fim (backend: `fila.enfileirar`);
 *  2. a tela não pode deduzir "em curso" só da ausência do campo.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SEM_FIM_REGISTRADO, duracaoDaExecucao, execucaoEmAberto, orientacaoDaExecucao } from "@/lib/estados";
import { avisoDoDisparo } from "@/lib/importacao";
import { ApiError } from "@/lib/api";
import { descreverErro, mensagemDoErro } from "@/lib/erros";
import type { ItemImportacaoSelecionada, ResultadoImportacaoSelecionada } from "@/lib/types";

function fonte(caminho: string): string {
  return readFileSync(resolve(__dirname, "..", caminho), "utf-8");
}

const INICIO = "2026-09-30T20:42:28Z";
const AGORA = Date.parse("2026-10-08T14:30:00Z");

describe("duração de execução não inventa trabalho em curso", () => {
  it("falha sem fim registrado não aparece 'em curso' e não cresce", () => {
    const falha = { status: "erro", iniciado_em: INICIO, finalizado_em: null };
    expect(execucaoEmAberto(falha)).toBe(false);
    expect(duracaoDaExecucao(falha, AGORA)).toBe(SEM_FIM_REGISTRADO);
    // Sem fim gravado, o texto não muda com o passar do tempo — não é cronômetro.
    expect(duracaoDaExecucao(falha, AGORA + 86_400_000)).toBe(SEM_FIM_REGISTRADO);
  });

  it("concluída sem fim registrado também admite a falta em vez de contar", () => {
    const concluida = { status: "concluida", iniciado_em: INICIO, finalizado_em: null };
    expect(duracaoDaExecucao(concluida, AGORA)).toBe(SEM_FIM_REGISTRADO);
  });

  it("execução realmente aberta continua dizendo 'em curso'", () => {
    for (const status of ["em_andamento", "aguardando"]) {
      expect(execucaoEmAberto({ status, finalizado_em: null })).toBe(true);
      expect(duracaoDaExecucao({ status, iniciado_em: INICIO, finalizado_em: null }, AGORA)).toBe("em curso");
    }
  });

  it("com fim registrado mostra a duração real, aberta ou não", () => {
    const fim = "2026-10-01T21:52:28Z";
    expect(duracaoDaExecucao({ status: "concluida", iniciado_em: INICIO, finalizado_em: fim }, AGORA)).toBe("1 dia");
    expect(execucaoEmAberto({ status: "em_andamento", finalizado_em: fim })).toBe(false);
  });
});

describe("telas de execução usam a regra, não o campo cru", () => {
  const telas = ["app/dashboard/execucoes/Execucoes.tsx", "app/dashboard/empresa/Empresa.tsx"];

  it("nenhuma célula decide 'em curso' só por finalizado_em", () => {
    for (const tela of telas) {
      const texto = fonte(tela).replace(/\s+/g, " ");
      expect(texto).not.toMatch(/finalizado_em \? tempoDecorrido\(/);
      expect(texto).toContain("duracaoDaExecucao(");
    }
  });

  it("o detalhe da execução diz o motivo do fim ausente", () => {
    const detalhe = fonte("app/dashboard/execucoes/Execucoes.tsx").replace(/\s+/g, " ");
    expect(detalhe).toContain("SEM_FIM_REGISTRADO");
    expect(detalhe).toContain("execucaoEmAberto(execucao)");
  });

  it("a borda que encerra a execução grava o fim (backend)", () => {
    const fila = fonte("../backend/app/services/fila.py").replace(/\s+/g, " ");
    const trecho = fila.slice(fila.indexOf("fila fora do ar não pode deixar execução zumbi"));
    expect(trecho).toContain("execucao.finalizado_em = datetime.now(timezone.utc)");
  });
});

describe("o próximo passo depende da natureza da falha", () => {
  it("fila fora do ar não manda conferir certificado nem promete consulta", () => {
    const texto = orientacaoDaExecucao("fila_indisponivel");
    expect(texto).toContain("Nada foi consultado na SEFAZ");
    expect(texto).not.toMatch(/certificado/i);
  });

  it("cadastro, ambiente fiscal, leitura parcial e sistema têm conselho próprio", () => {
    const textos = ["cadastro", "ambiente_fiscal", "importacao_parcial", "sistema"].map(orientacaoDaExecucao);
    expect(new Set(textos).size).toBe(textos.length);
    expect(orientacaoDaExecucao("cadastro")).not.toBe(orientacaoDaExecucao("captura"));
  });

  it("erro de captura e falha sem código (dado antigo) recebem o conselho fiscal", () => {
    const fiscal = orientacaoDaExecucao("captura");
    expect(orientacaoDaExecucao(null)).toBe(fiscal);
    expect(orientacaoDaExecucao(undefined)).toBe(fiscal);
    expect(orientacaoDaExecucao("codigo-que-nao-existe")).toBe(fiscal);
    expect(fiscal).toContain("certificado A1");
  });

  it("o detalhe da execução usa a orientação, não um texto fixo", () => {
    const detalhe = fonte("app/dashboard/execucoes/Execucoes.tsx").replace(/\s+/g, " ");
    expect(detalhe).toContain("orientacaoDaExecucao(execucao.falha)");
    expect(detalhe).not.toContain("Próximo passo: confira se o certificado A1 da empresa está válido");
  });
});

describe("o aviso do disparo diz o motivo real", () => {
  function item(status: string): ItemImportacaoSelecionada {
    return {
      empresa_id: 1, razao_social: "Empresa teste", tipo: "nfse", status,
      execucao_id: null, disponivel_em: null, mensagem: "", enfileirada: status === "enfileirada",
    };
  }
  function resultado(status: string, total = 1): ResultadoImportacaoSelecionada {
    const itens = Array.from({ length: total }, () => item(status));
    return {
      total: itens.length,
      enfileiradas: itens.filter((i) => i.enfileirada).length,
      aguardando: itens.filter((i) => i.status === "em_cooldown").length,
      ignoradas: itens.filter((i) => !i.enfileirada && i.status !== "em_cooldown").length,
      itens,
    };
  }

  it("fila indisponível não vira 'Nada a fazer neste recorte'", () => {
    const aviso = avisoDoDisparo(resultado("fila_indisponivel"), "10/2026");
    expect(aviso.tom).toBe("erro");
    expect(aviso.titulo).toBe("A fila de processamento não respondeu");
    expect(aviso.descricao).toContain("nada foi consultado na SEFAZ");
  });

  it("disparo misto: a falha da fila manda no aviso, sem esconder o que foi enfileirado", () => {
    const aviso = avisoDoDisparo(
      {
        total: 3,
        enfileiradas: 1,
        aguardando: 1,
        ignoradas: 1,
        itens: [item("enfileirada"), item("em_cooldown"), item("fila_indisponivel")],
      },
      "10/2026",
    );
    expect(aviso.tom).toBe("erro");
    expect(aviso.titulo).toBe("A fila de processamento não respondeu");
    expect(aviso.descricao).toContain("1 enfileiradas");
    expect(aviso.descricao).toContain("nada foi consultado na SEFAZ");
  });

  it("falta de cadastro também é explicada, em vez de recorte vazio", () => {
    const aviso = avisoDoDisparo(resultado("sem_certificado", 3), "10/2026");
    expect(aviso.tom).toBe("erro");
    expect(aviso.titulo).toContain("falta cadastro");
    expect(aviso.descricao).toContain("3 empresas");
  });

  it("enfileirada, janela em espera e recorte vazio seguem com o tom certo", () => {
    expect(avisoDoDisparo(resultado("enfileirada", 2), "10/2026").tom).toBe("ok");
    expect(avisoDoDisparo(resultado("em_cooldown", 2), "10/2026").titulo).toContain("janelas em espera");
    const vazio = avisoDoDisparo(resultado("ja_em_andamento"), "10/2026");
    expect(vazio.tom).toBe("info");
    expect(vazio.titulo).toBe("Nada a fazer neste recorte");
  });

  it("a tela de Importações usa o aviso do disparo, não a contagem crua", () => {
    const tela = fonte("app/dashboard/importacoes/Importacoes.tsx").replace(/\s+/g, " ");
    expect(tela).toContain("avisoDoDisparo(dados, rotuloPeriodo(periodo))");
    expect(tela).not.toContain('"Nada a fazer neste recorte"');
  });
});

describe("o erro de fila chega ao operador com o texto da API", () => {
  it("503 não vira 'falha interna' genérica sem o motivo", () => {
    const erro = new ApiError(503, "A fila de processamento não respondeu, então nada foi consultado na SEFAZ.");
    const descrito = descreverErro(erro, "disparar a importação");
    expect(descrito.tom).toBe("erro");
    expect(descrito.causa).toContain("A fila de processamento não respondeu");
    expect(descrito.proximoPasso).toContain("fila");
    expect(mensagemDoErro(erro, "disparar a importação")).toContain("A fila de processamento não respondeu");
  });
});
