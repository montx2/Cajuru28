"use client";

import { useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import { numero, plural } from "@/lib/format";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Busca, Selecao } from "@/components/ui/Campo";
import { Combobox } from "@/components/ui/Combobox";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { DataHora, Truncado } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { Paginacao } from "@/components/ui/Paginacao";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { ROTULO_ACAO, type RegistroAuditoria } from "@/lib/types";
import { ehAdmin, podeOperar } from "@/lib/papel";

const PASSO = 100;

/**
 * Auditoria: quem fez o quê, e quando.
 *
 * Somente leitura por decisão — não existe editar nem apagar registro aqui, nem
 * para admin. A tela diz isso em voz alta para que ninguém procure o botão.
 */
export function Auditoria() {
  const { definir, ler, lerNumero } = useUrlEstado();
  const { papel, carregando: carregandoSessao } = useSessao();
  const busca = useBuscaUrl();

  const acao = ler("acao");
  const limite = lerNumero("limite", PASSO) ?? PASSO;

  const registros = useRecurso(() => api.auditoria({ acao: acao || undefined, busca: busca.valor.trim() || undefined, limite }), [acao, busca.valor, limite]);
  const acoes = useRecurso(() => api.acoesAuditoria(), []);

  useSinalizarAtualizacao(registros.atualizando);

  // "Carregar mais" aqui é aumentar o limite na URL: a API não tem cursor.
  const carregarMais = useCallback(() => definir({ limite: limite + PASSO }), [definir, limite]);

  const colunas = useMemo<Array<ColunaTabela<RegistroAuditoria>>>(
    () => [
      { id: "quando", cabecalho: "Quando", ordenavel: true, largura: "w-48", celula: (registro) => <DataHora iso={registro.quando} /> },
      { id: "usuario", cabecalho: "Usuário", ordenavel: true, largura: "min-w-48", celula: (registro) => <span className="block truncate text-tinta">{registro.usuario_email || "sistema"}</span> },
      {
        id: "acao",
        cabecalho: "Ação",
        ordenavel: true,
        celula: (registro) => (
          <span className="flex items-center gap-2">
            <Etiqueta tom={tomDaAcao(registro.acao)}>{ROTULO_ACAO[registro.acao] ?? registro.acao}</Etiqueta>
          </span>
        ),
      },
      {
        id: "entidade",
        cabecalho: "Entidade",
        celula: (registro) =>
          registro.entidade ? (
            <span className="nums whitespace-nowrap text-tinta-suave">
              {registro.entidade}
              {registro.entidade_id !== null ? ` #${numero(registro.entidade_id)}` : ""}
            </span>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
      {
        id: "detalhe",
        cabecalho: "Detalhe",
        largura: "min-w-64",
        celula: (registro) => (registro.detalhe ? <Truncado texto={registro.detalhe} titulo={registro.detalhe} /> : <span className="text-tinta-fraca">—</span>),
      },
    ],
    []
  );

  if (!carregandoSessao && !podeOperar(papel)) {
    return (
      <EstadoVazio
        titulo="Seu papel não inclui auditoria"
        instrucao="O registro de ações é visível para operadores e administradores. Peça a um administrador se precisar consultar uma ação específica."
        icone="cadeado"
      />
    );
  }

  const linhas = registros.dados ?? [];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Auditoria"
        descricao="Registro imutável das ações executadas no sistema: login, cadastros, capturas, downloads e exclusões."
        acoes={
          <Botao variante="sutil" onClick={registros.atualizar} carregando={registros.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
            Atualizar
          </Botao>
        }
      />

      <Cartao densidade="compacta" className="nao-imprimir">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <Busca rotuloVisivel rotulo="Buscar na auditoria" placeholder="Usuário, entidade ou detalhe" valor={busca.valor} aoMudar={busca.aoMudar} />
          <Combobox
            rotulo="Ação"
            opcoes={[
              { valor: "", rotulo: "Todas as ações" },
              ...(acoes.dados ?? []).map((valor) => ({ valor, rotulo: ROTULO_ACAO[valor] ?? valor })),
            ]}
            valor={acao}
            aoMudar={(valor) => definir({ acao: valor || null, limite: null })}
            placeholder="Filtrar por ação"
            permiteLimpar
            carregando={acoes.carregando}
          />
          <Selecao
            rotulo="Registros por página"
            value={String(limite)}
            onChange={(evento) => definir({ limite: evento.target.value })}
            opcoes={[
              { valor: String(PASSO), rotulo: `${numero(PASSO)} mais recentes` },
              { valor: "250", rotulo: "250 mais recentes" },
              { valor: "500", rotulo: "500 mais recentes" },
              { valor: "1000", rotulo: "1.000 mais recentes" },
            ]}
          />
        </div>
      </Cartao>

      <Tabela
        linhas={linhas}
        colunas={colunas}
        chaveDaLinha={(registro) => registro.id}
        legenda="Registros de auditoria"
        virtualizar
        estados={{
          carregando: registros.carregando,
          erro: registros.erro,
          aoTentarNovamente: registros.atualizar,
          vazioTitulo: "Nenhum registro com este filtro",
          vazioInstrucao: "Ajuste a ação ou o termo buscado. Registros novos aparecem assim que a ação é executada.",
          vazioIcone: "auditoria",
          filtroAtivo: Boolean(acao || busca.valor.trim()),
          aoLimparFiltro: () => {
            definir({ acao: null, limite: null });
            busca.aoMudar("");
          },
        }}
        rodape={
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="nums text-xs text-tinta-suave">
              {numero(linhas.length)} {plural(linhas.length, "registro", "registros")} exibidos · mais recentes primeiro
              {ehAdmin(papel) ? " · visível para administradores e operadores" : ""}
            </p>
            <Paginacao
              total={linhas.length < limite ? linhas.length : limite + 1}
              exibidos={linhas.length}
              passo={PASSO}
              aoCarregarMais={linhas.length >= limite ? carregarMais : undefined}
              carregando={registros.atualizando}
            />
          </div>
        }
      />
    </div>
  );
}

/** Ações destrutivas e de acesso ganham tom; o resto é neutro para não gritar. */
function tomDaAcao(acao: string): "erro" | "espera" | "ok" | "neutro" {
  if (acao.includes("exclu") || acao.includes("reset")) return "erro";
  if (acao.includes("falha") || acao.includes("erro")) return "erro";
  if (acao.includes("login")) return "ok";
  if (acao.includes("exportacao") || acao.includes("zip") || acao.includes("csv")) return "espera";
  return "neutro";
}
