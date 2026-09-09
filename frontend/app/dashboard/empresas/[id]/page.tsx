"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Certificado, Empresa, TipoDocumentoFiscal } from "@/lib/types";

function formatarData(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR");
}

export default function DetalheEmpresaPage() {
  const { id } = useParams<{ id: string }>();
  const empresaId = Number(id);

  const [empresa, setEmpresa] = useState<Empresa | null>(null);
  const [certificados, setCertificados] = useState<Certificado[]>([]);
  const [senhaCertificado, setSenhaCertificado] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [enviandoCertificado, setEnviandoCertificado] = useState(false);
  const [erroCertificado, setErroCertificado] = useState<string | null>(null);
  const [disparandoImportacao, setDisparandoImportacao] = useState(false);
  const [mensagemImportacao, setMensagemImportacao] = useState<string | null>(null);

  function carregar() {
    api.obterEmpresa(empresaId).then(setEmpresa);
    api.listarCertificados(empresaId).then(setCertificados);
  }

  useEffect(carregar, [empresaId]);

  const certificadoAtivo = certificados.find((c) => c.ativo);

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
      setMensagemImportacao(`Importação de ${tipo.toUpperCase()} enfileirada (execução #${execucao.id}).`);
    } catch (e) {
      setMensagemImportacao(
        e instanceof ApiError ? e.message : "Não foi possível iniciar a importação."
      );
    } finally {
      setDisparandoImportacao(false);
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

  if (!empresa) return <p className="text-sm text-ink-muted">Carregando…</p>;

  return (
    <div className="max-w-3xl">
      <p className="font-serif text-2xl text-ink">{empresa.razao_social}</p>
      <p className="mb-8 font-mono text-sm text-ink-muted">{empresa.cnpj_cpf}</p>

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
        {mensagemImportacao && <p className="mt-4 text-sm text-ink-muted">{mensagemImportacao}</p>}
      </section>
    </div>
  );
}
