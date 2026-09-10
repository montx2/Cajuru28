"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { dataCurta } from "@/lib/format";
import { ROTULO_PAPEL, type Usuario } from "@/lib/types";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Esqueleto, EstadoVazio, TituloSecao } from "@/components/ui";

/**
 * Equipe do escritório (só admin): convida gente, troca papel e desliga acesso.
 * Desligar é `ativo=false` — nunca apaga, para a auditoria continuar íntegra.
 */
export default function UsuariosPage() {
  const toast = useToast();
  const { ehAdmin } = usePapel();
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [papel, setPapel] = useState("operador");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<number | null>(null);
  const [novoPapel, setNovoPapel] = useState("operador");

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setUsuarios(await api.listarUsuarios());
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 403)) {
        toast.erro("Não foi possível listar a equipe.");
      }
    } finally {
      setCarregando(false);
    }
  }, [toast]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  async function criar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setSalvando(true);
    try {
      await api.criarUsuario({ nome, email, senha, papel });
      toast.sucesso(`Usuário ${nome} criado.`);
      setNome("");
      setEmail("");
      setSenha("");
      setPapel("operador");
      setMostrarForm(false);
      carregar();
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Não foi possível criar o usuário.");
    } finally {
      setSalvando(false);
    }
  }

  async function salvarPapel(usuario: Usuario) {
    try {
      await api.atualizarUsuario(usuario.id, { papel: novoPapel });
      toast.sucesso(`Papel de ${usuario.nome} atualizado.`);
      setEditando(null);
      carregar();
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "Não foi possível atualizar.");
    }
  }

  async function alternarAtivo(usuario: Usuario) {
    try {
      await api.atualizarUsuario(usuario.id, { ativo: !usuario.ativo });
      toast.sucesso(usuario.ativo ? `${usuario.nome} desligado.` : `${usuario.nome} reativado.`);
      carregar();
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "Não foi possível atualizar.");
    }
  }

  async function redefinirSenha(usuario: Usuario) {
    const nova = window.prompt(`Nova senha para ${usuario.nome} (mínimo 6 caracteres):`);
    if (!nova) return;
    try {
      await api.atualizarUsuario(usuario.id, { senha: nova });
      toast.sucesso("Senha redefinida.");
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "Não foi possível redefinir.");
    }
  }

  if (!carregando && !ehAdmin) {
    return (
      <EstadoVazio
        icone="escudo"
        titulo="Acesso restrito"
        texto="Só administradores gerenciam a equipe. Fale com o admin do escritório."
      />
    );
  }

  return (
    <div className="animate-fade-up max-w-4xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink">Equipe</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Quem acessa o painel — e o que cada um pode fazer.
          </p>
        </div>
        <button type="button" onClick={() => setMostrarForm((v) => !v)} className="btn-primary btn-sm">
          <Icone nome="usuarios" className="h-4 w-4" />
          {mostrarForm ? "Fechar" : "Novo usuário"}
        </button>
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {[
          ["admin", "Administrador", "Tudo: opera, configura e gerencia a equipe."],
          ["operador", "Operador", "Cadastra, importa e baixa. Não mexe na equipe."],
          ["leitura", "Somente leitura", "Consulta e baixa XMLs. Não altera nada."],
        ].map(([id, titulo, texto]) => (
          <div key={id} className="card-pad">
            <p className="text-sm font-semibold text-ink">{titulo}</p>
            <p className="mt-1 text-xs text-ink-muted">{texto}</p>
          </div>
        ))}
      </div>

      {mostrarForm && (
        <form onSubmit={criar} className="card-pad mb-4">
          <TituloSecao titulo="Convidar para a equipe" />
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="u-nome">Nome</label>
              <input id="u-nome" required value={nome} onChange={(e) => setNome(e.target.value)} className="input" placeholder="Maria Silva" />
            </div>
            <div>
              <label className="label" htmlFor="u-email">Email (login)</label>
              <input id="u-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="input" placeholder="maria@escritorio.com.br" />
            </div>
            <div>
              <label className="label" htmlFor="u-senha">Senha inicial</label>
              <input id="u-senha" type="password" required minLength={6} value={senha} onChange={(e) => setSenha(e.target.value)} className="input" placeholder="mínimo 6 caracteres" />
            </div>
            <div>
              <label className="label" htmlFor="u-papel">Papel</label>
              <select id="u-papel" value={papel} onChange={(e) => setPapel(e.target.value)} className="input">
                <option value="operador">Operador</option>
                <option value="admin">Administrador</option>
                <option value="leitura">Somente leitura</option>
              </select>
            </div>
          </div>
          {erro && <p className="mt-3 text-sm text-danger">{erro}</p>}
          <button type="submit" disabled={salvando} className="btn-primary mt-4">
            {salvando ? "Criando…" : "Criar usuário"}
          </button>
        </form>
      )}

      {carregando ? (
        <div className="space-y-3">
          <Esqueleto className="h-16" />
          <Esqueleto className="h-16" />
        </div>
      ) : (
        <section className="card-pad">
          <div className="overflow-x-auto">
            <table className="tabela">
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Email</th>
                  <th>Papel</th>
                  <th>Situação</th>
                  <th>Desde</th>
                  <th className="text-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map((u) => (
                  <tr key={u.id} className={!u.ativo ? "opacity-60" : ""}>
                    <td className="font-medium text-ink">{u.nome}</td>
                    <td className="text-ink-muted">{u.email}</td>
                    <td>
                      {editando === u.id ? (
                        <span className="flex items-center gap-1">
                          <select value={novoPapel} onChange={(e) => setNovoPapel(e.target.value)} className="input py-1 text-xs">
                            <option value="admin">Administrador</option>
                            <option value="operador">Operador</option>
                            <option value="leitura">Somente leitura</option>
                          </select>
                          <button type="button" onClick={() => salvarPapel(u)} className="btn-primary btn-sm" title="Salvar papel">OK</button>
                          <button type="button" onClick={() => setEditando(null)} className="btn-ghost btn-sm">×</button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditando(u.id);
                            setNovoPapel(u.papel);
                          }}
                          title="Clique para trocar o papel"
                          className={
                            u.papel === "admin" ? "badge-ok" : u.papel === "operador" ? "badge-info" : "badge-neutral"
                          }
                        >
                          {ROTULO_PAPEL[u.papel] ?? u.papel}
                        </button>
                      )}
                    </td>
                    <td>
                      {u.ativo ? <span className="badge-ok">Ativo</span> : <span className="badge-danger">Desligado</span>}
                    </td>
                    <td className="font-mono text-xs text-ink-muted">{dataCurta(u.criado_em)}</td>
                    <td className="text-right">
                      <span className="inline-flex gap-1">
                        <button type="button" onClick={() => redefinirSenha(u)} className="btn-ghost btn-sm" title="Redefinir senha">
                          <Icone nome="chave" className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={() => alternarAtivo(u)} className="btn-ghost btn-sm" title={u.ativo ? "Desligar acesso" : "Reativar acesso"}>
                          <Icone nome={u.ativo ? "x" : "check"} className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
