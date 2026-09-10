"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { emQuanto, horaLocal } from "@/lib/competencia";
import { formatarDocumento } from "@/components/SeletorEmpresas";
import {
  ROTULO_TIPO,
  TIPOS,
  type Certificado,
  type EstadoSincronizacao,
  type Empresa,
  type TipoDocumentoFiscal,
} from "@/lib/types";

/**
 * Detalhe de uma empresa: certificado, sincronização e importação.
 *
 * Era uma rota dinâmica (`/empresas/[id]`). No build estático do modo desktop
 * rota dinâmica precisa ser declarada no build — e o id de uma empresa é dado
 * de runtime, não de compilação. Passar o id por `?id=` resolve sem nenhum
 * preço: o comportamento para quem usa é idêntico.
 *
 * O `Suspense` em volta é exigência do Next para páginas que leem a URL em
 * build estático (o resto da página é pré-renderizado, a parte que depende da
 * URL entra no cliente).
 */
export default function DetalheEmpresaPage() {
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">Carregando…</p>}>
      <ConteudoEmpresa />
    </Suspense>
  );
}

function formatarData(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR");
}

function ConteudoEmpresa() {
  const parametros = useSearchParams();
  const empresaId = Number(parametros.get("id") ?? 0);

  const [empresa, setEmpresa] = useState<Empresa | null>(null);
  const [certificados, setCertificados] = useState<Certificado[]>([]);
  const [senhaCertificado, setSenhaCertificado] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [enviandoCertificado, setEnviandoCertificado] = useState(false);
  const [erroCertificado, setErroCertificado] = useState<string | null>(null);
  const [disparandoImportacao, setDisparandoImportacao] = useState(false);
  const [mensagemImportacao, setMensagemImportacao] = useState<string | null>(null);
  const [sincronizacoes, setSincronizacoes] = useState<EstadoSincronizacao[]>([]);

  function carregar() {
    if (!empresaId) return;
    api
      .obterEmpresa(empresaId)
      .then(setEmpresa)
      .catch(() => setEmpresa(null));
    api.listarCertificados(empresaId).then(setCertificados).catch(() => setCertificados([]));
    api
      .sincronizacaoDaEmpresa(empresaId)
      .then(setSincronizacoes)
      .catch(() => setSincronizacoes([]));
  }

  useEffect(carregar, [empresaId]);

  const certificadoAtivo = certificados.find((c) => c.ativo);
  const automatico = empresa?.sincronizar_automaticamente !== false;

  async function enviarCertificado(evento: React.FormEvent) {
    evento.preventDefault();
    if (!arquivo) return;
    setErroCertificado(null);
    setEnviandoCertificado(true);
    try {
      await api.enviarCertificado(empresaId, senhaCertificado, arquivo);
      setSenhaCertificado("");
      setArquivo(null);
      carregar();
    } catch (e) {
      setErroCertificado(
        e instanceof ApiError ? e.message : "Não foi possível processar o certificado."
      );
    } finally {
      setEnviandoCertificado(false);
    }
  }

  async function importar(tipo: TipoDocumentoFiscal) {
    setDisparandoImportacao(true);
    setMensagemImportacao(null);
    try {
      const execucao = await api.solicitarImportacao(empresaId, tipo);
      setMensagemImportacao(`Importação de ${ROTULO_TIPO[tipo]} enfileirada (execução #${execucao.id}).`);
      carregar();
    } catch (e) {
      if (e instanceof ApiError && e.ehAguardo) {
        // A SEFAZ pede 1h entre consultas do mesmo CNPJ: é espera, não falha.
        setMensagemImportacao(e.message);
      } else {
        setMensagemImportacao(
          e instanceof ApiError ? e.message : "Não foi possível iniciar a importação."
        );
      }
    } finally {
      setDisparandoImportacao(false);
      carregar();
    }
  }

  async function alternarAutomatico() {
    if (!empresa) return;
    try {
      const atualizada = await api.atualizarEmpresa(empresa.id, {
        sincronizar_automaticamente: !empresa.sincronizar_automaticamente,
      });
      setEmpresa(atualizada);
    } catch (e) {
      setMensagemImportacao(e instanceof ApiError ? e.message : "Não foi possível alterar.");
    }
  }

  async function importarTodas() {
    setDisparandoImportacao(true);
    setMensagemImportacao(null);
    const tipos: TipoDocumentoFiscal[] = ["nfse", "nfe", "cte"];
    const ok: string[] = [];
    const falhas: string[] = [];
    for (const tipo of tipos) {
      try {
        const execucao = await api.solicitarImportacao(empresaId, tipo);
        ok.push(`${tipo.toUpperCase()} (#${execucao.id})`);
      } catch (e) {
        falhas.push(
          `${tipo.toUpperCase()}: ${e instanceof ApiError ? e.message : "falhou"}`
        );
      }
    }
    const partes: string[] = [];
    if (ok.length) partes.push(`Enfileiradas: ${ok.join(", ")}.`);
    if (falhas.length) partes.push(`Não iniciadas: ${falhas.join(" | ")}`);
    setMensagemImportacao(partes.join(" ") || "Nada foi enfileirado.");
    setDisparandoImportacao(false);
  }

  if (!empresaId) {
    return (
      <div className="max-w-3xl border border-line bg-surface p-6">
        <p className="text-sm text-ink-muted">
          Empresa não informada.{" "}
          <Link href="/dashboard/empresas" className="text-accent hover:underline">
            voltar para a lista
          </Link>
        </p>
      </div>
    );
  }

  if (!empresa) return <p className="text-sm text-ink-muted">Carregando…</p>;

  return (
    <div className="max-w-3xl">
      <Link href="/dashboard/empresas" className="text-xs text-accent hover:underline">
        ← empresas
      </Link>
      <p className="mt-2 font-serif text-2xl text-ink">{empresa.razao_social}</p>
      <p className="mb-8 font-mono text-sm text-ink-muted">
        {formatarDocumento(empresa.cnpj_cpf)} · {empresa.uf}
      </p>

      <section className="mb-6 border border-line bg-surface p-6">
        <p className="mb-4 text-base font-medium text-ink">Certificado A1</p>

        {certificadoAtivo ? (
          <p className="mb-4 text-sm text-ink-muted">
            Certificado ativo, válido até{" "}
            <span className="font-mono text-ink">{formatarData(certificadoAtivo.validade)}</span>.
            Envie um novo arquivo abaixo para substituí-lo (ex.: renovação anual).
          </p>
        ) : (
          <p className="mb-4 text-sm text-ink-muted">
            Nenhum certificado cadastrado ainda — a importação não funciona sem ele.
          </p>
        )}

        <form onSubmit={enviarCertificado} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm text-ink-muted">Arquivo .pfx</label>
            <input
              type="file"
              accept=".pfx,.p12"
              required
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              className="text-sm text-ink"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-ink-muted">Senha do certificado</label>
            <input
              type="password"
              required
              value={senhaCertificado}
              onChange={(e) => setSenhaCertificado(e.target.value)}
              className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </div>
          <button
            type="submit"
            disabled={enviandoCertificado}
            className="bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {enviandoCertificado ? "Enviando…" : "Enviar certificado"}
          </button>
        </form>
        {erroCertificado && <p className="mt-3 text-sm text-danger">{erroCertificado}</p>}
        <p className="mt-3 text-xs text-ink-muted">
          A senha é cifrada antes de gravar no banco e não pode ser vista novamente por aqui.
        </p>
      </section>

      <section className="border border-line bg-surface p-6">
        <p className="mb-2 text-base font-medium text-ink">Importar notas desta empresa</p>
        <p className="mb-4 text-sm text-ink-muted">
          As notas já entram classificadas em <strong>tomadas</strong> (empresa recebeu) ou{" "}
          <strong>prestadas</strong> (empresa emitiu). Use “Importar todas” para NFS-e, NFe e
          CT-e de uma vez.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => importarTodas()}
            disabled={disparandoImportacao || !certificadoAtivo}
            className="bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Importar todas
          </button>
          {(["nfse", "nfe", "cte"] as TipoDocumentoFiscal[]).map((tipo) => (
            <button
              key={tipo}
              type="button"
              onClick={() => importar(tipo)}
              disabled={disparandoImportacao || !certificadoAtivo}
              className="border border-accent px-4 py-2 text-sm font-medium text-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:border-line disabled:text-ink-muted"
            >
              Só {tipo.toUpperCase()}
            </button>
          ))}
        </div>
        {mensagemImportacao && (
          <p className="mt-4 border-l-2 border-warn bg-warn-soft px-3 py-2 text-sm text-ink">
            {mensagemImportacao}
          </p>
        )}
      </section>

      <section className="mt-6 border border-line bg-surface p-6">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-base font-medium text-ink">Sincronização automática</p>
          <button
            type="button"
            onClick={alternarAutomatico}
            className={
              automatico
                ? "bg-accent px-3 py-1.5 text-sm text-white hover:opacity-90"
                : "border border-line px-3 py-1.5 text-sm text-ink-muted hover:border-accent hover:text-ink"
            }
          >
            {automatico ? "Ligado — desligar" : "Desligado — ligar"}
          </button>
        </div>
        <p className="mb-4 text-sm text-ink-muted">
          Com o automático ligado, o sistema consulta esta empresa sozinho, respeitando a janela de
          1 hora por tipo de documento. Desligue apenas se outro sistema consultar o mesmo CNPJ na
          SEFAZ — aí os dois brigam pelo mesmo NSU.
        </p>

        <ul className="space-y-2 text-sm">
          {TIPOS.map((tipo) => {
            const estado = sincronizacoes.find((linha) => linha.tipo === tipo);
            const espera = emQuanto(estado?.bloqueado_ate ?? estado?.proxima_consulta_em ?? null);
            return (
              <li key={tipo} className="flex flex-wrap items-baseline gap-x-3 border-b border-line pb-2 last:border-0">
                <span className="w-16 text-ink">{ROTULO_TIPO[tipo]}</span>
                {!estado || Number(estado.ultimo_nsu) === 0 ? (
                  <span className="text-ink-muted">nunca consultado</span>
                ) : estado.em_dia ? (
                  <span className="text-accent">
                    em dia até o NSU {Number(estado.ultimo_nsu).toLocaleString("pt-BR")}
                  </span>
                ) : (
                  <span className="text-ink">
                    faltam {estado.pendencia} documento(s) · cursor {Number(estado.ultimo_nsu).toLocaleString("pt-BR")}
                    {estado.max_nsu ? ` / ${Number(estado.max_nsu).toLocaleString("pt-BR")}` : ""}
                  </span>
                )}
                {espera && <span className="text-warn">próxima consulta {espera}</span>}
                {estado?.ultima_consulta_em && (
                  <span className="text-xs text-ink-muted">
                    última varredura {horaLocal(estado.ultima_consulta_em)}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
