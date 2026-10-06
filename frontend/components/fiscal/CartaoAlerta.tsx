import Link from "next/link";
import { ROTULO_ACAO_LOTE } from "@/lib/acoes-documento";
import { BotaoLink } from "@/components/ui/Botao";
import { cn } from "@/lib/cn";
import { estadoDoNivel } from "@/lib/estados";
import { ROTULO_CATEGORIA_ALERTA, type AlertaItem } from "@/lib/types";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";

/**
 * Nenhum alerta pode nascer sem saída: quando a API não manda `acao_href`, a
 * categoria decide a tela que resolve. Alerta sem botão vira ruído e o operador
 * aprende a ignorar a lista mais importante do sistema.
 */
const ROTA_POR_CATEGORIA: Record<string, string> = {
  certificado: "/dashboard/certificados",
  cadastro: "/dashboard/empresas",
  sefaz: "/dashboard/importacoes",
  distribuicao: "/dashboard/importacoes",
  sincronismo: "/dashboard/importacoes",
  xml: "/dashboard/documentos?leiaute=resumo",
  execucao: "/dashboard/execucoes",
  sistema: "/dashboard/saude",
  procuracao: "/dashboard/procuracoes",
};

const FAIXA: Record<string, string> = {
  erro: "bg-erro",
  espera: "bg-espera",
  info: "bg-info",
  ok: "bg-ok",
  neutro: "bg-neutro",
  acento: "bg-acento",
};

export interface CartaoAlertaProps {
  alerta: AlertaItem;
  lida?: boolean;
  aoMarcarLida?: () => void;
  aoReabrir?: () => void;
  className?: string;
  /** Versão curta: sino do cabeçalho e resumo do Painel. */
  compacta?: boolean;
}

export function destinoDoAlerta(alerta: AlertaItem): string {
  if (alerta.acao_href) return alerta.acao_href;
  const rota = ROTA_POR_CATEGORIA[alerta.categoria] ?? "/dashboard/atencao";
  if (alerta.empresa_id && rota.startsWith("/dashboard/importacoes")) return `/dashboard/empresa?id=${alerta.empresa_id}&aba=sincronismo`;
  if (alerta.empresa_id && rota.startsWith("/dashboard/certificados")) return `/dashboard/empresa?id=${alerta.empresa_id}&aba=certificado`;
  return rota;
}

/**
 * Rótulo definitivo da ação de cada categoria.
 *
 * O fallback antigo era o mesmo para todas as categorias: um botão que não diz
 * o que faz exige ler o alerta inteiro antes do clique, e a mesma ação aparecia
 * com nomes diferentes em telas diferentes. Aqui o verbo é o da tela de destino
 * — `xml` usa exatamente o mesmo rótulo do acervo (Buscar todos os XMLs).
 */
const ROTULO_POR_CATEGORIA: Record<string, string> = {
  certificado: "Resolver certificado",
  cadastro: "Completar cadastro",
  sefaz: "Ver captura",
  distribuicao: "Ver captura",
  sincronismo: "Ver sincronismo",
  xml: ROTULO_ACAO_LOTE.buscarXml,
  execucao: "Ver execução",
  sistema: "Ver saúde do sistema",
  procuracao: "Ver procuração",
};

export function rotuloDaAcao(alerta: AlertaItem): string {
  if (alerta.acao_rotulo) return alerta.acao_rotulo;
  return ROTULO_POR_CATEGORIA[alerta.categoria] ?? "Ver detalhe";
}

export function CartaoAlerta({ alerta, lida, aoMarcarLida, aoReabrir, className, compacta }: CartaoAlertaProps) {
  const estado = estadoDoNivel(alerta.nivel);

  return (
    <article
      className={cn(
        "relative overflow-hidden rounded-cartao border bg-superficie pl-4 transition-colors duration-120",
        lida ? "border-traco opacity-70" : "border-traco hover:border-traco-forte",
        className
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", FAIXA[estado.tom])} />
      <div className={cn("flex flex-col gap-3 sm:flex-row sm:items-center", compacta ? "px-3 py-2.5" : "px-4 py-3")}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <IndicadorEstado {...estado} variante="etiqueta" />
            <span className="text-2xs uppercase tracking-[.04em] text-tinta-suave">
              {ROTULO_CATEGORIA_ALERTA[alerta.categoria] ?? alerta.categoria}
            </span>
            {alerta.empresa_razao_social ? (
              <Link
                href={`/dashboard/empresa?id=${alerta.empresa_id ?? ""}`}
                className="max-w-64 truncate text-xs text-tinta-suave underline-offset-4 hover:text-acento hover:underline"
                title={alerta.empresa_razao_social}
              >
                {alerta.empresa_razao_social}
              </Link>
            ) : null}
          </div>
          <h3 className={cn("mt-1.5 font-medium text-tinta-forte", compacta ? "text-sm" : "text-base")}>{alerta.titulo}</h3>
          <p
            className={cn("mt-0.5 text-sm leading-6 text-tinta-suave", compacta ? "line-clamp-2" : "max-w-leitura")}
            title={alerta.detalhe}
          >
            {alerta.detalhe}
          </p>
        </div>
        {/* Uma ação por alerta (a que resolve) + no máximo uma secundária
            ("Marcar como lida" OU "Reabrir", nunca as duas). Excluir/ignorar em
            massa não mora aqui. */}
        <div className="flex flex-none flex-wrap items-center gap-2">
          <BotaoLink
            data-acao="primaria"
            tamanho="sm"
            href={destinoDoAlerta(alerta)}
            iconeDireita={<Icone nome="seta-direita" className="h-3.5 w-3.5" />}
            className={cn(
              // Contorno, nunca preenchido: uma lista de alertas com botão
              // sólido em cada item vira parede de cor. A gravidade já está na
              // faixa, no selo e no tom do texto.
              estado.tom === "erro"
                ? "border-erro/45 text-erro hover:border-erro hover:bg-erro-tenue"
                : "border-borda-controle text-tinta hover:border-tinta-suave hover:bg-fundo-afundado"
            )}
          >
            {rotuloDaAcao(alerta)}
          </BotaoLink>
          {aoMarcarLida && !lida ? (
            <button
              type="button"
              data-acao="secundaria"
              onClick={aoMarcarLida}
              className="inline-flex h-9 items-center rounded-controle px-2 text-xs font-medium text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
            >
              Marcar como lida
            </button>
          ) : null}
          {aoReabrir && lida ? (
            <button
              type="button"
              data-acao="secundaria"
              onClick={aoReabrir}
              className="inline-flex h-9 items-center rounded-controle px-2 text-xs font-medium text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
            >
              Reabrir
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
