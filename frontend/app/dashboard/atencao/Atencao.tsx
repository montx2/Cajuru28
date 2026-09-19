"use client";

import { useMemo } from "react";
import { api } from "@/lib/api";
import { numero, plural } from "@/lib/format";
import { compararPorGravidade, estadoDoNivel } from "@/lib/estados";
import { usePreferencia } from "@/lib/usePreferencia";
import { useRecurso } from "@/lib/useRecurso";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useContagemAlertas } from "@/components/shell/ProvedorAlertas";
import { CartaoAlerta } from "@/components/fiscal/CartaoAlerta";
import { Abas, type Aba } from "@/components/ui/Abas";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Alternador, Busca, Selecao } from "@/components/ui/Campo";
import { EsqueletoLista } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Icone } from "@/components/ui/Icone";
import type { AlertaItem, NivelAlerta } from "@/lib/types";
import { ROTULO_CATEGORIA_ALERTA } from "@/lib/types";

/** Máximo de ids de alertas lidos guardados no navegador — evita lista eterna. */
const LIMITE_LIDAS = 200;

const NIVEIS: NivelAlerta[] = ["critico", "atencao", "info"];

/**
 * Fila de atenção: o que exige decisão, do mais grave para o menos grave.
 *
 * "Lida" é estado local do navegador (não há essa coluna na API) — serve para o
 * operador tirar da frente o item que já tratou sem esperar o próximo ciclo de
 * varredura. Por isso é reversível e nunca some de vez: o toggle mostra as lidas.
 */
export function Atencao() {
  const { definir, ler, lerBooleano } = useUrlEstado();
  const buscaCampo = useBuscaUrl();
  const { atualizar: atualizarContagem } = useContagemAlertas();
  const [lidas, setLidas] = usePreferencia<string[]>("alertas-lidos", []);

  const nivel = ler("nivel");
  const categoria = ler("categoria");
  const empresa = ler("empresa");
  const busca = buscaCampo.valor;
  const mostrarLidas = lerBooleano("lidas", false);

  const alertas = useRecurso(() => api.alertas(), []);
  const empresas = useRecurso(() => api.listarEmpresas(), []);
  useSinalizarAtualizacao(alertas.atualizando);

  const conjuntoLidas = useMemo(() => new Set(lidas), [lidas]);

  const filtrados = useMemo(() => {
    const itens = alertas.dados?.itens ?? [];
    const termo = busca.trim().toLocaleLowerCase("pt-BR");
    return itens
      .filter((alerta) => (nivel ? alerta.nivel === nivel : true))
      .filter((alerta) => (categoria ? alerta.categoria === categoria : true))
      .filter((alerta) => (empresa ? String(alerta.empresa_id ?? "") === empresa : true))
      .filter((alerta) => (mostrarLidas ? true : !conjuntoLidas.has(alerta.id)))
      .filter((alerta) =>
        termo
          ? `${alerta.titulo} ${alerta.detalhe} ${alerta.empresa_razao_social ?? ""} ${alerta.categoria}`
              .toLocaleLowerCase("pt-BR")
              .includes(termo)
          : true
      )
      .sort(compararPorGravidade);
  }, [alertas.dados, busca, categoria, conjuntoLidas, empresa, mostrarLidas, nivel]);

  const grupos = useMemo(
    () =>
      NIVEIS.map((nivelGrupo) => ({
        nivel: nivelGrupo,
        estado: estadoDoNivel(nivelGrupo),
        itens: filtrados.filter((alerta) => alerta.nivel === nivelGrupo),
      })).filter((grupo) => grupo.itens.length > 0),
    [filtrados]
  );

  const categorias = useMemo(() => {
    const encontradas = new Set((alertas.dados?.itens ?? []).map((alerta) => alerta.categoria));
    return Array.from(encontradas)
      .sort()
      .map((valor) => ({ valor, rotulo: ROTULO_CATEGORIA_ALERTA[valor] ?? valor }));
  }, [alertas.dados]);

  const abas: Aba[] = [
    { valor: "", rotulo: "Todos", contador: alertas.dados?.total },
    ...NIVEIS.map((nivelAba) => ({
      valor: nivelAba as string,
      rotulo: estadoDoNivel(nivelAba).rotulo,
      contador: (alertas.dados?.itens ?? []).filter((alerta) => alerta.nivel === nivelAba).length,
    })),
  ];

  const filtroAtivo = Boolean(nivel || categoria || empresa || busca || mostrarLidas);

  function marcarLida(alerta: AlertaItem) {
    setLidas((atual) => [alerta.id, ...atual.filter((id) => id !== alerta.id)].slice(0, LIMITE_LIDAS));
    atualizarContagem();
  }

  function reabrir(alerta: AlertaItem) {
    setLidas((atual) => atual.filter((id) => id !== alerta.id));
  }

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Precisa da sua atenção"
        descricao={
          alertas.dados
            ? `${numero(alertas.dados.total)} ${plural(alertas.dados.total, "item", "itens")} em aberto · ${numero(alertas.dados.criticos)} ${plural(alertas.dados.criticos, "crítico", "críticos")} · ${numero(alertas.dados.atencao)} importantes`
            : "Decisões pendentes da operação, em ordem de gravidade"
        }
        acoes={
          <Botao
            variante="secundaria"
            onClick={() => {
              alertas.atualizar();
              atualizarContagem();
            }}
            carregando={alertas.atualizando || alertas.carregando}
            iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
          >
            Atualizar
          </Botao>
        }
      />

      <Abas rotulo="Nível do alerta" idBase="nivel-alerta" abas={abas} valor={nivel} aoMudar={(valor) => definir({ nivel: valor || null })} />

      <Cartao densidade="compacta" className="nao-imprimir">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Busca
            rotulo="Buscar nos alertas"
            placeholder="Título, detalhe ou empresa"
            valor={buscaCampo.valor}
            aoMudar={buscaCampo.aoMudar}
          />
          <Selecao
            rotulo="Categoria"
            value={categoria}
            onChange={(evento) => definir({ categoria: evento.target.value || null })}
            opcoes={[{ valor: "", rotulo: "Todas as categorias" }, ...categorias]}
          />
          <Selecao
            rotulo="Empresa"
            value={empresa}
            onChange={(evento) => definir({ empresa: evento.target.value || null })}
            opcoes={[
              { valor: "", rotulo: "Todas as empresas" },
              ...(empresas.dados ?? []).map((empresaItem) => ({ valor: String(empresaItem.id), rotulo: empresaItem.razao_social })),
            ]}
          />
          <Alternador
            rotulo="Mostrar alertas lidos"
            descricao="Estado salvo neste navegador"
            ligado={mostrarLidas}
            aoMudar={(valor) => definir({ lidas: valor ? "1" : null })}
          />
        </div>
      </Cartao>

      {alertas.carregando ? (
        <EsqueletoLista itens={5} linhas={2} />
      ) : alertas.erro ? (
        <EstadoErro erro={alertas.erro} aoTentarNovamente={alertas.atualizar} contexto="carregar a fila de atenção" />
      ) : grupos.length === 0 ? (
        filtroAtivo ? (
          <EstadoVazio
            titulo="Nenhum alerta com estes filtros"
            instrucao={
              mostrarLidas
                ? "Todos os itens deste recorte já foram marcados como lidos neste navegador."
                : "Ajuste o nível, a categoria ou a busca para ver outros itens."
            }
            acao={
              <Botao
                variante="secundaria"
                onClick={() => definir({ nivel: null, categoria: null, empresa: null, busca: null, lidas: null })}
                iconeEsquerda={<Icone nome="remover" className="h-4 w-4" />}
              >
                Limpar filtros
              </Botao>
            }
            icone="filtrar"
          />
        ) : (
          <EstadoVazio
            titulo="Nada em aberto"
            instrucao="A captura automática está em dia e nenhum certificado, empresa ou execução exige decisão agora."
            icone="verificar-circulo"
          />
        )
      ) : (
        <div className="space-y-6">
          {grupos.map((grupo) => (
            <section key={grupo.nivel} aria-labelledby={`grupo-${grupo.nivel}`}>
              <div className="mb-2 flex items-baseline gap-2">
                <h2 id={`grupo-${grupo.nivel}`} className="text-sm font-semibold text-tinta-forte">
                  {grupo.estado.rotulo}
                </h2>
                <span className="nums text-xs text-tinta-suave">
                  {numero(grupo.itens.length)} {plural(grupo.itens.length, "item", "itens")}
                </span>
              </div>
              <ul className="space-y-2">
                {grupo.itens.map((alerta) => (
                  <li key={alerta.id}>
                    <CartaoAlerta
                      alerta={alerta}
                      lida={conjuntoLidas.has(alerta.id)}
                      aoMarcarLida={() => marcarLida(alerta)}
                      aoReabrir={() => reabrir(alerta)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
