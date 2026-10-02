import { describe, expect, it } from "vitest";
import { estadoDaSincronizacao } from "@/lib/estados";
import type { EstadoSincronizacao } from "@/lib/types";

const agora = Date.parse("2026-10-02T15:00:00Z");
const base: EstadoSincronizacao = {
  empresa_id: 1, razao_social: "Empresa teste", tipo: "nfse", ultimo_nsu: "100", max_nsu: "100",
  pendencia: 0, em_dia: true, bloqueado_ate: null, motivo_bloqueio: null,
  bloqueios_seguidos: 0, proxima_consulta_em: null, ultima_consulta_em: "2026-10-02T14:00:00Z",
  liberacao_em: null, segundos_para_liberar: 0, liberacao_rotulo: "liberado",
  em_andamento: false, travado: false, sincronizar_automaticamente: true,
  cota_pontual_disponivel: 20, dias_sem_varrer: 0, risco_documento_fora_da_distribuicao: false,
};

describe("captura honesta: cursor não prova que todos os itens foram lidos", () => {
  it("não anuncia em dia se um lote recebido está ilegível", () => {
    const visual = estadoDaSincronizacao({ ...base, lotes_pendentes: 1 }, agora);
    expect(visual.tom).toBe("erro");
    expect(visual.rotulo).toBe("Importação parcial");
    expect(visual.absoluto).toContain("1 lote recebido precisa");
  });

  it("mostra a falha de leitura mesmo durante uma janela fiscal", () => {
    const visual = estadoDaSincronizacao({ ...base, lotes_pendentes: 2, liberacao_em: "2026-10-02T16:00:00Z" }, agora);
    expect(visual.rotulo).toBe("Importação parcial");
    expect(visual.absoluto).toContain("2 lotes recebidos precisam");
  });

  it("uma retomada realmente ativa aparece em processamento", () => {
    expect(estadoDaSincronizacao({ ...base, lotes_pendentes: 1, em_andamento: true }, agora).rotulo).toBe("Varrendo agora");
  });

  it("maxNSU desconhecido não vira selo de acervo completo", () => {
    const visual = estadoDaSincronizacao({ ...base, max_nsu: null, em_dia: false, nunca_consultado: true }, agora);
    expect(visual.tom).toBe("neutro");
    expect(visual.rotulo).toBe("Cursor não confirmado");
  });

  it("preserva em dia quando o máximo é confirmado e nada ficou pendente", () => {
    expect(estadoDaSincronizacao(base, agora).rotulo).toBe("Em dia");
  });
});
