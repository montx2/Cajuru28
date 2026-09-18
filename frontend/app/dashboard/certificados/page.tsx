"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { dataHora, formatarCnpjCpf, tempoRelativo } from "@/lib/format";
import type { CertificadoPainel } from "@/lib/types";
import { Icone } from "@/components/icons";
import { BuscaInput } from "@/components/Busca";
import { useToast } from "@/components/Toast";
import { Esqueleto, EstadoVazio, KpiCard, TituloSecao } from "@/components/ui";

type Filtro = "todos" | "vencidos" | "vencendo" | "sem" | "ok";

const FILTROS: { id: Filtro; rotulo: string }[] = [
  { id: "todos", rotulo: "Todos" },
  { id: "vencidos", rotulo: "Vencidos" },
  { id: "vencendo", rotulo: "Vencendo (30 d)" },
  { id: "sem", rotulo: "Sem certificado" },
  { id: "ok", rotulo: "Saudáveis" },
];

function classeStatus(item: CertificadoPainel): string {
  if (!item.tem_certificado || item.vencido) return "badge-danger";
  if (item.vence_em_breve) return "badge-warn";
  return "badge-ok";
}

function rotuloStatus(item: CertificadoPainel): string {
  if (!item.tem_certificado) return "Sem certificado";
  if (item.vencido) return "Vencido";
  if (item.vence_em_breve) return `Vence em ${item.dias_para_vencer} d`;
  return "Válido";
}

/**
 * Centro de certificados — o A1 é o coração da autenticação fiscal.
 *
 * Tudo de cada certificado num só lugar: validade, dias restantes, última
 * utilização real numa varredura e o erro da última autenticação. A senha
 * jamais aparece — nem em texto, nem em log.
 */
export default function CertificadosPage() {
  const toast = useToast();
  const [itens, setItens] = useState<CertificadoPainel[] | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [busca, setBusca] = useState("");

  const [modalEmpresa, setModalEmpresa] = useState<CertificadoPainel | null>(null);
  const [senha, setSenha] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [enviando, setEnviando] = useState(false);
  const campoArquivo = useRef<HTMLInputElement>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setItens(await api.painelCertificados());
    } catch {
      setItens(null);
      toast.erro("Não foi possível carregar os certificados.");
    } finally {
      setCarregando(false);
    }
  }, [toast]);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, 120_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  async function substituir(e: React.FormEvent) {
    e.preventDefault();
    if (!modalEmpresa || !arquivo) return;
    setEnviando(true);
    try {
      await api.enviarCertificado(modalEmpresa.empresa_id, senha, arquivo);
      toast.sucesso(`Certificado de ${modalEmpresa.razao_social} substituído.`);
      setModalEmpresa(null);
      setSenha("");
      setArquivo(null);
      carregar();
    } catch (err) {
      toast.erro(err instanceof Error ? err.message : "Falha ao enviar certificado.");
    } finally {
      setEnviando(false);
    }
  }

  const contagem = useMemo(() => {
    const base = itens ?? [];
    return {
      vencidos: base.filter((i) => i.vencido).length,
      vencendo: base.filter((i) => i.tem_certificado && i.vence_em_breve && !i.vencido).length,
      sem: base.filter((i) => !i.tem_certificado).length,
      ok: base.filter((i) => i.tem_certificado && !i.vencido && !i.vence_em_breve).length,
    };
  }, [itens]);

  const visiveis = useMemo(() => {
    let lista = itens ?? [];
    if (filtro === "vencidos") lista = lista.filter((i) => i.vencido);
    else if (filtro === "vencendo") lista = lista.filter((i) => i.vence_em_breve && !i.vencido);
    else if (filtro === "sem") lista = lista.filter((i) => !i.tem_certificado);
    else if (filtro === "ok") lista = lista.filter((i) => i.tem_certificado && !i.vencido && !i.vence_em_breve);
    const termo = busca.trim().toLowerCase();
    if (termo) {
      lista = lista.filter(
        (i) =>
          i.razao_social.toLowerCase().includes(termo) ||
          i.cnpj_cpf.includes(termo.replace(/\D/g, ""))
      );
    }
    return lista;
  }, [itens, filtro, busca]);

  return (
    <div className="animate-fade-up space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Certificados</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Validade, última utilização e saúde de cada A1 — troque antes de virar incêndio.
          </p>
        </div>
        <button type="button" onClick={carregar} className="btn-ghost btn-sm">
          <Icone nome="atualizar" className="h-4 w-4" /> Atualizar
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard icone="xCirculo" rotulo="Vencidos" valor={String(contagem.vencidos)} tom={contagem.vencidos ? "perigo" : "ok"} />
        <KpiCard icone="alerta" rotulo="Vencendo em 30 d" valor={String(contagem.vencendo)} tom={contagem.vencendo ? "alerta" : "ok"} />
        <KpiCard icone="escudo" rotulo="Sem certificado" valor={String(contagem.sem)} tom={contagem.sem ? "alerta" : "ok"} />
        <KpiCard icone="checkCirculo" rotulo="Saudáveis" valor={String(contagem.ok)} tom="ok" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFiltro(f.id)}
            className={filtro === f.id ? "btn-primary btn-sm" : "btn-ghost btn-sm"}
          >
            {f.rotulo}
          </button>
        ))}
        <BuscaInput
          valor={busca}
          aoMudar={setBusca}
          placeholder="Empresa ou CNPJ…"
          className="sm:ml-auto sm:w-72"
          ariaLabel="Buscar certificado por empresa ou CNPJ"
        />
      </div>

      {carregando && !itens ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Esqueleto key={i} className="h-14" />
          ))}
        </div>
      ) : !itens ? (
        <EstadoVazio icone="escudo" titulo="Não foi possível carregar" />
      ) : visiveis.length === 0 ? (
        <EstadoVazio
          icone="escudo"
          titulo="Nenhum certificado neste filtro"
          texto="Cadastre empresas com certificado A1 para a importação automática funcionar."
          acao={
            <Link href="/dashboard/empresas" className="btn-primary btn-sm">
              Cadastrar empresas
            </Link>
          }
        />
      ) : (
        <div className="card overflow-x-auto">
          <table className="tabela">
            <thead>
              <tr>
                <th>Empresa</th>
                <th>Status</th>
                <th>Validade</th>
                <th>Última utilização</th>
                <th>Saúde da autenticação</th>
                <th className="text-right">Ação</th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((item) => (
                <tr key={item.empresa_id}>
                  <td>
                    <Link href={`/dashboard/empresa?id=${item.empresa_id}`} className="font-medium hover:underline">
                      {item.razao_social}
                    </Link>
                    <span className="block font-mono text-xs text-ink-faint">
                      {formatarCnpjCpf(item.cnpj_cpf)}
                    </span>
                  </td>
                  <td>
                    <span className={classeStatus(item)}>{rotuloStatus(item)}</span>
                  </td>
                  <td className="whitespace-nowrap font-mono text-xs">
                    {item.validade ? dataHora(item.validade) : "—"}
                  </td>
                  <td className="whitespace-nowrap text-xs" title={item.ultima_utilizacao_em ? dataHora(item.ultima_utilizacao_em) : undefined}>
                    {item.ultima_utilizacao_em ? tempoRelativo(item.ultima_utilizacao_em) : "nunca"}
                  </td>
                  <td className="max-w-72">
                    {item.ultimo_erro ? (
                      <span className="line-clamp-1 text-xs text-danger" title={item.ultimo_erro}>
                        {item.ultimo_erro}
                      </span>
                    ) : item.tem_certificado ? (
                      <span className="text-xs text-ink-muted">
                        {item.ultima_utilizacao_em ? "autenticando normalmente" : "ainda não usado em varredura"}
                      </span>
                    ) : (
                      <span className="text-xs text-ink-faint">—</span>
                    )}
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      onClick={() => {
                        setModalEmpresa(item);
                        setSenha("");
                        setArquivo(null);
                      }}
                      className="btn-ghost btn-sm"
                    >
                      <Icone nome="atualizar" className="h-4 w-4" />
                      {item.tem_certificado ? "Substituir" : "Enviar"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-ink-faint">
        A senha do certificado é cifrada no cofre local e jamais exibida. Os arquivos
        .pfx ficam em pasta com acesso restrito ao próprio sistema.
      </p>

      {/* ---- modal de substituição ---- */}
      {modalEmpresa && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4 backdrop-blur-sm">
          <form onSubmit={substituir} className="card w-full max-w-md p-6 shadow-pop">
            <h2 className="font-serif text-xl font-semibold text-ink">
              {modalEmpresa.tem_certificado ? "Substituir" : "Enviar"} certificado
            </h2>
            <p className="mt-1 text-sm text-ink-muted">
              {modalEmpresa.razao_social} · {formatarCnpjCpf(modalEmpresa.cnpj_cpf)}
            </p>

            <div className="mt-4 space-y-3">
              <div>
                <label className="label" htmlFor="arquivo-pfx">
                  Arquivo .pfx (A1)
                </label>
                <input
                  id="arquivo-pfx"
                  ref={campoArquivo}
                  type="file"
                  accept=".pfx,.p12"
                  onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
                  className="input"
                  required
                />
              </div>
              <div>
                <label className="label" htmlFor="senha-pfx">
                  Senha do certificado
                </label>
                <input
                  id="senha-pfx"
                  type="password"
                  value={senha}
                  onChange={(e) => setSenha(e.target.value)}
                  className="input"
                  autoComplete="new-password"
                  required
                />
                <p className="mt-1 text-xs text-ink-faint">
                  A senha é cifrada imediatamente e nunca fica em texto aberto.
                </p>
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setModalEmpresa(null)} className="btn-ghost btn-sm">
                Cancelar
              </button>
              <button type="submit" disabled={!arquivo || !senha || enviando} className="btn-primary btn-sm">
                {enviando ? "Enviando…" : "Salvar"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
