"use client";

import { cn } from "@/lib/cn";
import { dataCurta, dataHora, numero, tempoRelativo } from "@/lib/format";
import { estadoDoCertificado } from "@/lib/estados";
import type { CertificadoPainel, ResumoCertificado } from "@/lib/types";
import { Botao } from "@/components/ui/Botao";
import { Dado } from "@/components/ui/Dado";
import { Cnpj } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { useAgora } from "@/components/shell/ProvedorAgora";

export interface CartaoCertificadoProps {
  certificado: ResumoCertificado & Partial<CertificadoPainel>;
  aoSubstituir?: () => void;
  carregando?: boolean;
  somenteLeitura?: boolean;
  className?: string;
}

/**
 * Certificado é ativo crítico: sem A1 válido toda importação da empresa falha.
 * O cartão mostra validade, dias restantes, última utilização **real** e o
 * último erro de autenticação — a senha nunca aparece, nem preenchida, nem
 * mascarada: ela é aberta no cofre e descartada.
 */
export function CartaoCertificado({ certificado, aoSubstituir, carregando, somenteLeitura, className }: CartaoCertificadoProps) {
  const agora = useAgora();
  const estado = estadoDoCertificado(certificado);
  const detalhe = certificado as CertificadoPainel;

  return (
    <section className={cn("rounded-cartao border border-traco bg-superficie p-4", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-tinta-forte" title={certificado.razao_social}>
            {certificado.razao_social}
          </h3>
          <Cnpj valor={detalhe.cnpj_cpf} className="mt-0.5" />
        </div>
        <IndicadorEstado {...estado} titulo={certificado.validade ? `Validade: ${dataHora(certificado.validade)}` : undefined} />
      </header>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
        <Dado rotulo="Validade" valor={certificado.validade ? dataCurta(certificado.validade) : "—"} dica={dataHora(certificado.validade)} />
        <Dado
          rotulo="Dias restantes"
          valor={certificado.dias_para_vencer === null || certificado.dias_para_vencer === undefined ? "—" : numero(certificado.dias_para_vencer)}
          tom={estado.tom}
        />
        <Dado
          rotulo="Última utilização real"
          valor={detalhe.ultima_utilizacao_em ? tempoRelativo(detalhe.ultima_utilizacao_em, agora) : "nunca usado"}
          dica={dataHora(detalhe.ultima_utilizacao_em ?? null)}
        />
        <Dado rotulo="Última validação" valor={detalhe.ultima_validacao_em ? tempoRelativo(detalhe.ultima_validacao_em, agora) : "—"} dica={dataHora(detalhe.ultima_validacao_em ?? null)} />
        <Dado
          className="col-span-2"
          rotulo="Último erro de autenticação"
          valor={detalhe.ultimo_erro ?? "nenhum"}
          tom={detalhe.ultimo_erro ? "erro" : undefined}
          linhas={2}
        />
      </dl>

      {certificado.vencido ? (
        <p className="mt-3 flex items-start gap-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
          <Icone nome="risco" className="mt-0.5 h-4 w-4 flex-none" />
          <span>Toda importação desta empresa vai falhar até a substituição do A1.</span>
        </p>
      ) : null}

      {aoSubstituir ? (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-traco pt-3">
          <Botao
            variante={certificado.vencido || !certificado.tem_certificado ? "primaria" : "secundaria"}
            tamanho="sm"
            onClick={aoSubstituir}
            carregando={carregando}
            disabled={somenteLeitura}
            title={somenteLeitura ? "Seu papel é somente leitura" : undefined}
            iconeEsquerda={<Icone nome="certificado" className="h-4 w-4" />}
          >
            {certificado.tem_certificado ? "Substituir A1" : "Enviar A1"}
          </Botao>
          <p className="text-xs text-tinta-suave">A senha abre o arquivo no cofre e não é guardada em texto claro.</p>
        </div>
      ) : null}
    </section>
  );
}

