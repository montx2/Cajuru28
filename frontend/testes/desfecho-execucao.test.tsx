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
import { SEM_FIM_REGISTRADO, duracaoDaExecucao, execucaoEmAberto } from "@/lib/estados";

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
