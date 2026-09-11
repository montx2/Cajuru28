"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { formatarDocumento } from "@/components/SeletorEmpresas";
import {
  type Certificado,
  type Empresa,
} from "@/lib/types";

/**
 * Detalhe de uma empresa: certificado, sincronização e importação.
 *
 * O id é passado por `?id=`, mantendo a página simples e o comportamento
 * idêntico para quem usa.
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
  const { somenteLeitura } = usePapel();

  function carregar() {
    if (!empresaId) return;
    api
      .obterEmpresa(empresaId)
      .then(setEmpresa)
      .catch(() => setEmpresa(null));
    api.listarCertificados(empresaId).then(setCertificados).catch(() => setCertificados([]));
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
              className="input"
            />
          </div>
          <button
            type="submit"
            disabled={enviandoCertificado || somenteLeitura}
            title={somenteLeitura ? "Seu perfil é somente leitura." : undefined}
            className="btn-primary disabled:opacity-50"
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
        <p className="mb-2 text-base font-medium text-ink">Importação de notas</p>
        <p className="mb-4 text-sm text-ink-muted">
          Para evitar consultas duplicadas e bloqueios por consumo indevido, novas importações só
          podem ser iniciadas na aba Importações, sempre com uma competência informada.
        </p>
        <Link href="/dashboard/importacoes" className="btn-primary inline-block">
          Ir para Importações
        </Link>
      </section>
    </div>
  );
}
