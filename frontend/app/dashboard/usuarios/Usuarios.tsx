"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { numero, plural } from "@/lib/format";
import { MOTIVO_SOMENTE_LEITURA, ehAdmin } from "@/lib/papel";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Alternador, Busca, Entrada, Selecao } from "@/components/ui/Campo";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { DataHora } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Modal } from "@/components/ui/Modal";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import { ROTULO_PAPEL, type PapelUsuario, type Usuario } from "@/lib/types";

const PAPEIS: PapelUsuario[] = ["admin", "operador", "leitura"];
const FILTROS = [
  { valor: "", rotulo: "Toda a equipe" },
  { valor: "ativos", rotulo: "Ativos" },
  { valor: "inativos", rotulo: "Desativados" },
  ...PAPEIS.map((papel) => ({ valor: papel, rotulo: ROTULO_PAPEL[papel] })),
];

const DESCRICAO_PAPEL: Record<PapelUsuario, string> = {
  admin: "Configura, cadastra, dispara captura e gerencia a equipe.",
  operador: "Dispara captura, envia certificados e trata alertas. Não gerencia usuários.",
  leitura: "Consulta e baixa relatórios. Nenhuma ação que altere dados.",
};

/**
 * Equipe e papéis.
 *
 * Não existe exclusão de usuário — só desativação: o registro precisa continuar
 * existindo para a auditoria fazer sentido. E ninguém altera o próprio papel ou
 * a própria situação: é o jeito mais barato de travar o escritório inteiro.
 */
export function Usuarios() {
  const { definir, ler } = useUrlEstado();
  const busca = useBuscaUrl();
  const { usuario: sessao, papel: papelSessao, carregando: carregandoSessao } = useSessao();

  const filtro = ler("filtro");
  const ordem = ler("ordem") || "nome";
  const sentido = ler("sentido") === "desc" ? "desc" : "asc";

  const [criando, setCriando] = useState(false);
  const [editando, setEditando] = useState<Usuario | null>(null);

  const usuarios = useRecurso(() => api.listarUsuarios(), []);
  useSinalizarAtualizacao(usuarios.atualizando);

  const linhas = useMemo(() => {
    const termo = busca.valor.trim().toLocaleLowerCase("pt-BR");
    const resultado = (usuarios.dados ?? []).filter((usuario) => {
      if (termo && !`${usuario.nome} ${usuario.email}`.toLocaleLowerCase("pt-BR").includes(termo)) return false;
      switch (filtro) {
        case "ativos":
          return usuario.ativo;
        case "inativos":
          return !usuario.ativo;
        case "admin":
        case "operador":
        case "leitura":
          return usuario.papel === filtro;
        default:
          return true;
      }
    });
    const fator = sentido === "asc" ? 1 : -1;
    return [...resultado].sort((a, b) => {
      switch (ordem) {
        case "email":
          return fator * a.email.localeCompare(b.email, "pt-BR");
        case "papel":
          return fator * (PAPEIS.indexOf(a.papel as PapelUsuario) - PAPEIS.indexOf(b.papel as PapelUsuario));
        case "situacao":
          return fator * (Number(b.ativo) - Number(a.ativo));
        case "criado":
          return fator * (new Date(a.criado_em).getTime() - new Date(b.criado_em).getTime());
        default:
          return fator * a.nome.localeCompare(b.nome, "pt-BR");
      }
    });
  }, [busca.valor, filtro, ordem, sentido, usuarios.dados]);

  const colunas = useMemo<Array<ColunaTabela<Usuario>>>(
    () => [
      {
        id: "nome",
        cabecalho: "Nome",
        largura: "min-w-48",
        fixa: true,
        ordenavel: true,
        celula: (usuario) => (
          <span className="block truncate font-medium text-tinta-forte">
            {usuario.nome}
            {usuario.id === sessao?.id ? <span className="ml-2 text-xs font-normal text-tinta-suave">você</span> : null}
          </span>
        ),
      },
      { id: "email", cabecalho: "E-mail", ordenavel: true, celula: (usuario) => <span className="block truncate text-tinta">{usuario.email}</span> },
      {
        id: "papel",
        cabecalho: "Papel",
        ordenavel: true,
        celula: (usuario) => (
          <Etiqueta tom={usuario.papel === "admin" ? "acento" : usuario.papel === "operador" ? "info" : "neutro"} titulo={DESCRICAO_PAPEL[(usuario.papel as PapelUsuario) ?? "leitura"]}>
            {ROTULO_PAPEL[(usuario.papel as PapelUsuario) ?? "leitura"] ?? usuario.papel}
          </Etiqueta>
        ),
      },
      {
        id: "situacao",
        cabecalho: "Situação",
        ordenavel: true,
        celula: (usuario) =>
          usuario.ativo ? (
            <IndicadorEstado tom="ok" rotulo="Ativo" icone="verificar-circulo" />
          ) : (
            <IndicadorEstado tom="neutro" rotulo="Desativado" icone="pausa" titulo="Não entra no sistema; os registros de auditoria permanecem" />
          ),
      },
      { id: "criado", cabecalho: "Criado em", alinhamento: "direita", ordenavel: true, celula: (usuario) => <DataHora iso={usuario.criado_em} /> },
      {
        id: "acoes",
        cabecalho: "",
        alinhamento: "direita",
        celula: (usuario) => (
          <Botao
            variante="sutil"
            tamanho="sm"
            onClick={() => setEditando(usuario)}
            disabled={usuario.id === sessao?.id}
            title={usuario.id === sessao?.id ? "Você não edita o próprio acesso: peça a outro administrador" : "Editar nome, papel e situação"}
          >
            Editar
          </Botao>
        ),
      },
    ],
    [sessao?.id]
  );

  if (!carregandoSessao && !ehAdmin(papelSessao)) {
    return (
      <EstadoVazio
        titulo="Somente administradores gerenciam a equipe"
        instrucao="Seu papel não inclui criação nem alteração de usuários. Peça a um administrador para criar acessos ou mudar papéis."
        icone="cadeado"
      />
    );
  }

  const admin = papelSessao === "admin";

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Equipe"
        descricao="Quem entra no NotasFlow e o que cada papel pode fazer. Desativar mantém o histórico de auditoria."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={usuarios.atualizar} carregando={usuarios.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            <Botao
              variante="primaria"
              onClick={() => setCriando(true)}
              disabled={!admin}
              title={admin ? undefined : MOTIVO_SOMENTE_LEITURA}
              iconeEsquerda={<Icone nome="adicionar" className="h-4 w-4" />}
            >
              Novo usuário
            </Botao>
          </div>
        }
      />

      {(usuarios.dados ?? []).some((usuario) => usuario.papel === "admin" && usuario.ativo) === false ? (
        <Aviso tom="erro" icone="risco" titulo="Nenhum administrador ativo">
          Sem administrador ativo ninguém gerencia certificados, equipe nem integrações. Reative um admin nesta tela — a ação vale para o seu próprio
          registro apenas com outro administrador.
        </Aviso>
      ) : null}

      <Tabela
        linhas={linhas}
        colunas={colunas}
        chaveDaLinha={(usuario) => usuario.id}
        legenda="Usuários do escritório"
        ordenacao={{ coluna: ordem, direcao: sentido }}
        aoOrdenar={(proxima) => definir({ ordem: proxima?.coluna ?? null, sentido: proxima?.direcao ?? null })}
        estados={{
          carregando: usuarios.carregando,
          erro: usuarios.erro,
          aoTentarNovamente: usuarios.atualizar,
          vazioTitulo: "Nenhum usuário com este filtro",
          vazioInstrucao: "Crie o primeiro acesso com nome, e-mail e papel — a senha inicial deve ser trocada pelo usuário.",
          vazioIcone: "equipe",
          filtroAtivo: Boolean(filtro || busca.valor.trim()),
          aoLimparFiltro: () => {
            definir({ filtro: null, busca: null });
            busca.aoMudar("");
          },
        }}
        ferramentas={
          <div className="flex flex-wrap items-end gap-2">
            <Busca rotuloVisivel rotulo="Buscar usuário" placeholder="Nome ou e-mail" valor={busca.valor} aoMudar={busca.aoMudar} className="min-w-56 flex-1" />
            <Selecao
              rotulo="Filtro"
              className="w-56"
              value={filtro}
              onChange={(evento) => definir({ filtro: evento.target.value || null })}
              opcoes={FILTROS}
            />
          </div>
        }
        rodape={
          <p className="nums text-xs text-tinta-suave">
            {numero(linhas.length)} {plural(linhas.length, "usuário", "usuários")} · {numero((usuarios.dados ?? []).filter((usuario) => usuario.ativo).length)} ativos ·{" "}
            {numero((usuarios.dados ?? []).filter((usuario) => usuario.papel === "admin" && usuario.ativo).length)} administradores
          </p>
        }
      />

      <ModalUsuario aberto={criando} aoFechar={() => setCriando(false)} aoSalvar={usuarios.atualizar} />
      <ModalUsuario aberto={editando !== null} usuario={editando} aoFechar={() => setEditando(null)} aoSalvar={usuarios.atualizar} />
    </div>
  );
}

function ModalUsuario({
  aberto,
  aoFechar,
  aoSalvar,
  usuario,
}: {
  aberto: boolean;
  aoFechar: () => void;
  aoSalvar: () => void;
  usuario?: Usuario | null;
}) {
  const { avisar } = useToast();
  const edicao = Boolean(usuario);
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [papel, setPapel] = useState<PapelUsuario>("leitura");
  const [ativo, setAtivo] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [errosCampo, setErrosCampo] = useState<{ nome?: string; email?: string; senha?: string }>({});

  // Abre sempre com o estado do usuário escolhido (ou vazio, na criação).
  useEffect(() => {
    if (!aberto) return;
    setNome(usuario?.nome ?? "");
    setEmail(usuario?.email ?? "");
    setSenha("");
    setPapel((usuario?.papel as PapelUsuario) ?? "leitura");
    setAtivo(usuario?.ativo ?? true);
    setErro(null);
    setErrosCampo({});
  }, [aberto, usuario]);

  async function salvar() {
    const proximosErros: typeof errosCampo = {};
    if (!nome.trim()) proximosErros.nome = "Informe o nome de quem vai usar o sistema.";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) proximosErros.email = "Informe um e-mail válido — é com ele que a pessoa entra.";
    if (!edicao && senha.length < 8) proximosErros.senha = "A senha inicial precisa de ao menos 8 caracteres.";
    if (edicao && senha && senha.length < 8) proximosErros.senha = "A nova senha precisa de ao menos 8 caracteres.";
    setErrosCampo(proximosErros);
    if (Object.keys(proximosErros).length > 0) return;

    setEnviando(true);
    setErro(null);
    try {
      if (edicao && usuario) {
        await api.atualizarUsuario(usuario.id, { nome: nome.trim(), email: email.trim(), papel, ativo, ...(senha ? { senha } : {}) });
        avisar({ tom: "ok", titulo: "Usuário atualizado", descricao: `${nome.trim()} · ${ROTULO_PAPEL[papel]}` });
      } else {
        await api.criarUsuario({ nome: nome.trim(), email: email.trim(), senha, papel });
        avisar({ tom: "ok", titulo: "Usuário criado", descricao: `${nome.trim()} · ${ROTULO_PAPEL[papel]} · senha inicial definida por você` });
      }
      aoSalvar();
      aoFechar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível salvar o usuário.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={aoFechar}
      titulo={edicao ? `Editar ${usuario?.nome ?? "usuário"}` : "Novo usuário"}
      descricao={edicao ? "Mudar o papel altera imediatamente o que essa pessoa vê e pode fazer." : "A pessoa entra com e-mail e senha; a sessão fica em cookie HttpOnly."}
      largura="media"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={aoFechar}>
            Cancelar
          </Botao>
          <Botao variante="primaria" onClick={salvar} carregando={enviando}>
            {edicao ? "Salvar alterações" : "Criar usuário"}
          </Botao>
        </div>
      }
    >
      <div className="space-y-4">
        <Entrada rotulo="Nome" obrigatorio value={nome} onChange={(evento) => setNome(evento.target.value)} erro={errosCampo.nome ?? null} autoComplete="off" />
        <Entrada rotulo="E-mail" obrigatorio type="email" inputMode="email" value={email} onChange={(evento) => setEmail(evento.target.value)} erro={errosCampo.email ?? null} autoComplete="off" />
        <Entrada
          rotulo={edicao ? "Nova senha (opcional)" : "Senha inicial"}
          obrigatorio={!edicao}
          type="password"
          value={senha}
          onChange={(evento) => setSenha(evento.target.value)}
          erro={errosCampo.senha ?? null}
          descricao={edicao ? "Deixe em branco para manter a senha atual." : "Mínimo de 8 caracteres. Peça para a pessoa trocar no primeiro acesso."}
          autoComplete={edicao ? "new-password" : "off"}
        />
        <Selecao
          rotulo="Papel"
          obrigatorio
          value={papel}
          onChange={(evento) => setPapel(evento.target.value as PapelUsuario)}
          descricao={DESCRICAO_PAPEL[papel]}
          opcoes={PAPEIS.map((item) => ({ valor: item, rotulo: ROTULO_PAPEL[item] }))}
        />
        {edicao ? (
          <Alternador
            rotulo="Acesso ativo"
            descricao="Desativado, a pessoa não entra — mas os registros de auditoria dela permanecem."
            ligado={ativo}
            aoMudar={setAtivo}
          />
        ) : null}
        {erro ? (
          <p role="alert" className="flex items-start gap-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
            <Icone nome="alerta" className="mt-1 h-4 w-4 flex-none" />
            <span>{erro}</span>
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
