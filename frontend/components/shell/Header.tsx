"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { ROTULO_PAPEL, type AlertaItem, type PapelUsuario } from "@/lib/types";
import { migalhasDoCaminho } from "@/lib/rotas";
import { useTeclaModificadora } from "@/lib/useTeclaModificadora";
import { CartaoAlerta } from "@/components/fiscal/CartaoAlerta";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { Icone } from "@/components/ui/Icone";
import { MenuSuspenso, type ItemMenu } from "@/components/ui/MenuSuspenso";
import { Migalhas } from "@/components/ui/Migalhas";
import { Popover, PopoverCabecalho } from "@/components/ui/Popover";
import { Spinner } from "@/components/ui/Spinner";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { SeletorTema } from "./SeletorTema";
import { useComandos } from "./ProvedorComandos";
import { useContagemAlertas } from "./ProvedorAlertas";
import { useSessao } from "./ProvedorSessao";

/**
 * Cabeçalho de 56 px: trilha, busca global, tema, alertas e usuário.
 *
 * A "caixa de busca" abre a paleta em vez de ser um input solto: um campo que
 * não filtra nada ali seria controle morto, e a paleta já busca tela, empresa e
 * documento com o mesmo gesto (`Ctrl/⌘K`).
 */
export function Header({ aoAbrirMenu }: { aoAbrirMenu: () => void }) {
  const caminho = usePathname();
  const { abrirPaleta, abrirAtalhos } = useComandos();
  const { simbolo } = useTeclaModificadora();

  return (
    <header className="nao-imprimir sticky top-0 z-cabecalho flex h-14 flex-none items-center gap-2 border-b border-traco bg-superficie px-3 sm:px-4">
      <button
        type="button"
        onClick={aoAbrirMenu}
        aria-label="Abrir menu de navegação"
        className="flex h-10 w-10 flex-none items-center justify-center rounded-controle text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta lg:hidden"
      >
        <Icone nome="menu" className="h-5 w-5" />
      </button>

      <div className="min-w-0 flex-none">
        <Migalhas className="hidden sm:flex" itens={migalhasDoCaminho(caminho)} />
      </div>

      <button
        type="button"
        onClick={abrirPaleta}
        className="mx-auto flex h-9 w-full max-w-md items-center gap-2 rounded-controle border border-borda-controle bg-superficie-alta px-2.5 text-sm text-tinta-suave transition-colors duration-120 hover:border-traco-forte hover:text-tinta"
      >
        <Icone nome="busca" className="h-4 w-4 flex-none" />
        <span className="min-w-0 flex-1 truncate text-left">Buscar tela, empresa ou documento</span>
        <kbd className="hidden flex-none rounded-badge border border-traco bg-fundo-afundado px-1.5 py-0.5 font-mono text-2xs sm:inline">
          {simbolo} K
        </kbd>
      </button>

      <div className="ml-auto flex flex-none items-center gap-1">
        <SeletorTema />
        <SinoAlertas />
        <MenuUsuario aoAbrirAtalhos={abrirAtalhos} />
      </div>
    </header>
  );
}

/** Sino com contagem já conhecida (polling do shell) e lista buscada ao abrir. */
function SinoAlertas() {
  const { contagem, atualizar } = useContagemAlertas();
  const tomContador = contagem.criticos > 0 ? ("erro" as const) : contagem.atencao > 0 ? ("espera" as const) : ("neutro" as const);

  return (
    <Popover
      rotulo="Alertas"
      icone="sino"
      contador={contagem.total}
      tomContador={tomContador}
      dica={contagem.total > 0 ? `${contagem.total} em aberto` : "Nada em aberto"}
      alinhamento="direita"
      largura="w-[min(92vw,26rem)]"
    >
      {(fechar) => <ConteudoSino aoFechar={fechar} aoAtualizarContagem={atualizar} />}
    </Popover>
  );
}

function ConteudoSino({ aoFechar, aoAtualizarContagem }: { aoFechar: () => void; aoAtualizarContagem: () => void }) {
  const [resposta, setResposta] = useState<{ itens: AlertaItem[]; total: number } | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<unknown>(null);
  const [tentativa, setTentativa] = useState(0);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    api
      .alertas()
      .then((dados) => {
        if (!vivo) return;
        setResposta({ itens: dados.itens ?? [], total: dados.total ?? 0 });
        setErro(null);
      })
      .catch((falha: unknown) => {
        if (vivo) setErro(falha);
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [tentativa]);

  return (
    <div>
      <PopoverCabecalho
        titulo="Precisa da sua atenção"
        acao={
          <button
            type="button"
            onClick={() => {
              aoAtualizarContagem();
              setTentativa((atual) => atual + 1);
            }}
            className="rounded-badge px-1 py-0.5 text-xs font-medium text-acento underline-offset-4 hover:underline"
          >
            Atualizar
          </button>
        }
      />

      <div className="rolagem-fina max-h-96 overflow-y-auto p-2">
        {carregando ? (
          <p className="flex items-center gap-2 px-2 py-6 text-sm text-tinta-suave" aria-busy="true">
            <Spinner />
            Carregando alertas…
          </p>
        ) : erro ? (
          <EstadoErro
            erro={erro}
            aoTentarNovamente={() => setTentativa((atual) => atual + 1)}
            contexto="carregar os alertas"
          />
        ) : resposta && resposta.itens.length > 0 ? (
          <ul className="space-y-1.5" onClick={aoFechar}>
            {resposta.itens.slice(0, 5).map((alerta) => (
              <li key={alerta.id}>
                <CartaoAlerta alerta={alerta} compacta />
              </li>
            ))}
            {resposta.total > 5 ? (
              <li className="px-2 pt-1 text-xs text-tinta-suave">
                e mais {resposta.total - 5} — veja todos na tela de atenção.
              </li>
            ) : null}
          </ul>
        ) : (
          <div className="flex items-center gap-3 px-2 py-6 text-sm text-tinta-suave">
            <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full border border-ok/30 bg-ok-tenue text-ok" aria-hidden="true">
              <Icone nome="verificar-circulo" className="h-4 w-4" />
            </span>
            Nada em aberto. A operação está em dia.
          </div>
        )}
      </div>

      <div className="border-t border-traco bg-fundo-afundado px-3 py-2">
        <Link
          href="/dashboard/atencao"
          onClick={aoFechar}
          className="flex h-8 items-center gap-1.5 text-xs font-medium text-acento underline-offset-4 hover:underline"
        >
          Ver tela de atenção
          <Icone nome="chevron-direita" className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}

function MenuUsuario({ aoAbrirAtalhos }: { aoAbrirAtalhos: () => void }) {
  const { usuario, papel, sair } = useSessao();
  const [confirmandoSaida, setConfirmandoSaida] = useState(false);
  const rotuloPapel = ROTULO_PAPEL[(papel as PapelUsuario) ?? "leitor"] ?? papel;

  const itens: ItemMenu[] = [
    { id: "configuracoes", rotulo: "Configurações", icone: "configuracoes", href: "/dashboard/configuracoes" },
    { id: "saude", rotulo: "Saúde do sistema", icone: "saude", href: "/dashboard/saude" },
    { id: "atalhos", rotulo: "Atalhos de teclado", icone: "teclado", atalho: "?", aoClicar: aoAbrirAtalhos, separarAcima: true },
    { id: "sair", rotulo: "Sair", icone: "sair", tom: "perigo", aoClicar: () => setConfirmandoSaida(true) },
  ];

  return (
    <>
      <MenuSuspenso rotulo={usuario?.nome ?? "Conta"} itens={itens} alinhamento="direita" largura="w-64">
        <div className="border-b border-traco px-3 pb-2.5 pt-2">
          <p className="truncate text-sm font-medium text-tinta-forte">{usuario?.nome ?? "Sem sessão"}</p>
          <p className="truncate text-xs text-tinta-suave">{usuario?.email ?? "Não autenticado"}</p>
          <p className="mt-1.5">
            <span className="rounded-badge border border-traco bg-neutro-tenue px-1.5 py-0.5 text-2xs font-medium text-neutro">
              {rotuloPapel || "—"}
            </span>
          </p>
          {usuario?.escritorio_nome ? (
            <p className="mt-1.5 truncate text-2xs text-tinta-fraca">Escritório: {usuario.escritorio_nome}</p>
          ) : null}
        </div>
      </MenuSuspenso>

      {/* Sair encerra cookie e perde contexto de filtros: confirma antes. */}
      <DialogoConfirmacao
        aberto={confirmandoSaida}
        aoFechar={() => setConfirmandoSaida(false)}
        tom="perigo"
        titulo="Encerrar sessão"
        consequencia="Você precisará entrar novamente com e-mail e senha. Preferências salvas neste navegador permanecem."
        rotuloConfirmar="Sair"
        aoConfirmar={async () => {
          setConfirmandoSaida(false);
          await sair();
        }}
      />
    </>
  );
}
