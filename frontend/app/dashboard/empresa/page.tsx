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
  type JettaxConfiguracaoEmpresa,
  type JettaxExecucao,
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
  const [jettax, setJettax] = useState<JettaxConfiguracaoEmpresa | null>(null);
  const [execucoesJettax, setExecucoesJettax] = useState<JettaxExecucao[]>([]);
  const [codigoIbge, setCodigoIbge] = useState("");
  const [inscricaoMunicipal, setInscricaoMunicipal] = useState("");
  const [jettaxAtiva, setJettaxAtiva] = useState(false);
  const [baixarNfes, setBaixarNfes] = useState(true);
  const [baixarNfesEnviadas, setBaixarNfesEnviadas] = useState(false);
  const [enviarCertificadoJettax, setEnviarCertificadoJettax] = useState(false);
  const [ocupadoJettax, setOcupadoJettax] = useState(false);
  const [erroJettax, setErroJettax] = useState<string | null>(null);
  const [mensagemJettax, setMensagemJettax] = useState<string | null>(null);
  const { ehAdmin, podeOperar, somenteLeitura } = usePapel();

  function carregar() {
    if (!empresaId) return;
    api
      .obterEmpresa(empresaId)
      .then((dados) => {
        setEmpresa(dados);
        setCodigoIbge(dados.codigo_ibge ?? "");
        setInscricaoMunicipal(dados.inscricao_municipal ?? "");
      })
      .catch(() => setEmpresa(null));
    api.listarCertificados(empresaId).then(setCertificados).catch(() => setCertificados([]));
    api
      .obterJettaxEmpresa(empresaId)
      .then((dados) => {
        setJettax(dados);
        setJettaxAtiva(Boolean(dados.ativa));
        const nuncaConfigurada =
          dados.status === "nao_registrada" &&
          !dados.atualizado_em &&
          !dados.baixar_nfes &&
          !dados.baixar_nfes_enviadas;
        setBaixarNfes(nuncaConfigurada ? true : Boolean(dados.baixar_nfes));
        setBaixarNfesEnviadas(Boolean(dados.baixar_nfes_enviadas));
      })
      .catch(() => setJettax(null));
    api
      .listarExecucoesJettaxEmpresa(empresaId, 12)
      .then(setExecucoesJettax)
      .catch(() => setExecucoesJettax([]));
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

  function jettaxRegistrada(config: JettaxConfiguracaoEmpresa | null): boolean {
    return config?.status === "registrada" || config?.status === "atualizada";
  }

  function rotuloFluxoJettax(fluxo: string): string {
    if (fluxo === "purchases") return "NF-e recebidas";
    if (fluxo === "sales") return "NF-e emitidas";
    return "NFS-e";
  }

  function formatarDataHora(iso?: string | null): string {
    if (!iso) return "—";
    return new Date(iso).toLocaleString("pt-BR");
  }

  async function salvarDadosJettaxLocal(): Promise<JettaxConfiguracaoEmpresa> {
    await api.atualizarEmpresa(empresaId, {
      ...(codigoIbge.trim() ? { codigo_ibge: codigoIbge.trim() } : {}),
      ...(inscricaoMunicipal.trim() ? { inscricao_municipal: inscricaoMunicipal.trim() } : {}),
    });
    const config = await api.salvarJettaxEmpresa(empresaId, {
      ativa: jettaxAtiva,
      baixar_nfes: baixarNfes,
      baixar_nfes_enviadas: baixarNfesEnviadas,
    });
    setJettax(config);
    return config;
  }

  async function salvarJettax() {
    setErroJettax(null);
    setMensagemJettax(null);
    setOcupadoJettax(true);
    try {
      await salvarDadosJettaxLocal();
      setMensagemJettax("Preferências Jettax salvas. Se a empresa já estiver registrada, clique em atualizar cadastro remoto.");
      carregar();
    } catch (e) {
      setErroJettax(e instanceof ApiError ? e.message : "Não foi possível salvar a configuração Jettax.");
    } finally {
      setOcupadoJettax(false);
    }
  }

  async function sincronizarCadastroJettax() {
    if (!ehAdmin) return;
    setErroJettax(null);
    setMensagemJettax(null);
    setOcupadoJettax(true);
    try {
      const salvo = await salvarDadosJettaxLocal();
      const atualizado = jettaxRegistrada(salvo)
        ? await api.atualizarClienteJettaxEmpresa(empresaId, enviarCertificadoJettax)
        : await api.registrarJettaxEmpresa(empresaId, enviarCertificadoJettax);
      setJettax(atualizado);
      setMensagemJettax(
        atualizado.status === "registrada"
          ? jettaxAtiva
            ? "Cliente criado na Jettax. A integração desta empresa está pronta para consultar documentos."
            : "Cliente criado na Jettax. Marque “Ativar integração” para liberar consultas e fallback automático."
          : jettaxAtiva
            ? "Cliente remoto reconciliado e atualizado na Jettax."
            : "Cliente remoto reconciliado e atualizado. Marque “Ativar integração” para liberar consultas e fallback automático."
      );
      carregar();
    } catch (e) {
      setErroJettax(e instanceof ApiError ? e.message : "Não foi possível registrar a empresa na Jettax.");
    } finally {
      setOcupadoJettax(false);
    }
  }

  async function importarJettax(tipo: "nfse" | "purchases" | "sales") {
    setErroJettax(null);
    setMensagemJettax(null);
    setOcupadoJettax(true);
    try {
      const execucao =
        tipo === "nfse"
          ? await api.importarNFSeJettax(empresaId)
          : await api.importarNFeJettax(empresaId, { direcao: tipo });
      setMensagemJettax(`Verificação Jettax enfileirada (#${execucao.id}).`);
      const lista = await api.listarExecucoesJettaxEmpresa(empresaId, 12);
      setExecucoesJettax(lista);
    } catch (e) {
      setErroJettax(e instanceof ApiError ? e.message : "Não foi possível enfileirar a importação Jettax.");
    } finally {
      setOcupadoJettax(false);
    }
  }

  if (!empresaId) {
    return (
      <div className="card-pad max-w-3xl">
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
    <div className="animate-fade-up max-w-3xl">
      <Link href="/dashboard/empresas" className="link text-xs">← Empresas</Link>
      <div className="mb-8 mt-5">
        <p className="page-kicker">Cadastro fiscal</p>
        <h1 className="page-title">{empresa.razao_social}</h1>
        <p className="mt-2 font-mono text-sm text-ink-muted">
          {formatarDocumento(empresa.cnpj_cpf)} · {empresa.uf}
        </p>
      </div>

      <section className="card-pad mb-6">
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
            <label className="label">Arquivo .pfx</label>
            <input
              type="file"
              accept=".pfx,.p12"
              required
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              className="text-sm text-ink"
            />
          </div>
          <div>
            <label className="label">Senha do certificado</label>
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

      <section className="card-pad mb-6">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-base font-medium text-ink">Jettax 360 como fallback</p>
            <p className="mt-1 text-sm text-ink-muted">
              A fonte oficial continua principal. Se SEFAZ/ADN bloquear, falhar ou concluir uma
              consulta, o sistema aciona a Jettax automaticamente para conferir e importar o que ela
              encontrar — desde que esta empresa esteja ativa e registrada abaixo.
            </p>
          </div>
          <span className={jettaxRegistrada(jettax) && jettaxAtiva ? "badge-ok" : "badge-neutral"}>
            {jettaxRegistrada(jettax) && jettaxAtiva ? "fallback ativo" : "fallback pendente"}
          </span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold text-ink-muted">
            Código IBGE do município
            <input
              className="input mt-1 w-full font-mono"
              value={codigoIbge}
              onChange={(e) => setCodigoIbge(e.target.value.replace(/\D/g, "").slice(0, 7))}
              placeholder="ex.: 3133808"
              disabled={!ehAdmin || ocupadoJettax}
            />
          </label>
          <label className="text-xs font-semibold text-ink-muted">
            Inscrição municipal / CCM
            <input
              className="input mt-1 w-full"
              value={inscricaoMunicipal}
              onChange={(e) => setInscricaoMunicipal(e.target.value)}
              placeholder="número cadastrado na prefeitura"
              disabled={!ehAdmin || ocupadoJettax}
            />
          </label>
        </div>

        <div className="mt-4 grid gap-2 text-sm text-ink-muted sm:grid-cols-3">
          <label className="flex items-start gap-2 rounded-lg border border-line bg-bg p-3">
            <input
              type="checkbox"
              checked={jettaxAtiva}
              onChange={(e) => setJettaxAtiva(e.target.checked)}
              disabled={!ehAdmin || ocupadoJettax}
              className="mt-1 accent-accent"
            />
            <span>
              <strong className="block text-ink">Ativar integração</strong>
              liberar consultas manuais e fallback automático desta empresa
            </span>
          </label>
          <label className="flex items-start gap-2 rounded-lg border border-line bg-bg p-3">
            <input
              type="checkbox"
              checked={baixarNfes}
              onChange={(e) => setBaixarNfes(e.target.checked)}
              disabled={!ehAdmin || ocupadoJettax}
              className="mt-1 accent-accent"
            />
            <span>
              <strong className="block text-ink">NF-e recebidas</strong>
              capturar compras/entradas pela Jettax
            </span>
          </label>
          <label className="flex items-start gap-2 rounded-lg border border-line bg-bg p-3">
            <input
              type="checkbox"
              checked={baixarNfesEnviadas}
              onChange={(e) => setBaixarNfesEnviadas(e.target.checked)}
              disabled={!ehAdmin || ocupadoJettax}
              className="mt-1 accent-accent"
            />
            <span>
              <strong className="block text-ink">NF-e emitidas</strong>
              capturar vendas/saídas pela Jettax
            </span>
          </label>
        </div>

        <div className="mt-4 rounded-lg border border-line bg-bg px-3 py-2 text-xs text-ink-muted">
          <p>
            Status remoto: <strong className="text-ink">{jettax?.status ?? "não carregado"}</strong>
            {jettax?.ultima_sincronizacao_em
              ? ` · última captura ${formatarDataHora(jettax.ultima_sincronizacao_em)}`
              : ""}
          </p>
          <p className="mt-1">
            Cursores: NFS-e <span className="font-mono">{jettax?.ultimo_id_nfse ?? "—"}</span> · NF-e
            recebidas <span className="font-mono">{jettax?.ultimo_id_nfe_entrada ?? "—"}</span> · NF-e
            emitidas <span className="font-mono">{jettax?.ultimo_id_nfe_saida ?? "—"}</span>
          </p>
          {jettax?.ultimo_erro && <p className="mt-1 text-danger">Último erro: {jettax.ultimo_erro}</p>}
        </div>

        {erroJettax && <p className="mt-3 text-sm text-danger">{erroJettax}</p>}
        {mensagemJettax && <p className="mt-3 text-sm text-accent-deep">{mensagemJettax}</p>}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          {ehAdmin ? (
            <>
              <button type="button" onClick={salvarJettax} disabled={ocupadoJettax} className="btn-ghost">
                {ocupadoJettax ? "Aguarde…" : "Salvar preferências"}
              </button>
              <button
                type="button"
                onClick={sincronizarCadastroJettax}
                disabled={ocupadoJettax}
                className="btn-primary disabled:opacity-50"
              >
                {jettaxRegistrada(jettax) ? "Atualizar cadastro remoto" : "Registrar na Jettax"}
              </button>
              <label className="flex items-center gap-2 text-xs text-ink-muted">
                <input
                  type="checkbox"
                  checked={enviarCertificadoJettax}
                  onChange={(e) => setEnviarCertificadoJettax(e.target.checked)}
                  disabled={ocupadoJettax}
                  className="accent-accent"
                />
                enviar A1 à Jettax nesta chamada
              </label>
            </>
          ) : (
            <span className="text-xs text-ink-muted">Somente administradores registram/alteram a Jettax.</span>
          )}
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!podeOperar || ocupadoJettax || !jettaxRegistrada(jettax) || !jettaxAtiva}
            onClick={() => importarJettax("nfse")}
            className="btn-ghost btn-sm disabled:opacity-50"
          >
            Conferir NFS-e agora
          </button>
          <button
            type="button"
            disabled={!podeOperar || ocupadoJettax || !jettaxRegistrada(jettax) || !jettaxAtiva}
            onClick={() => importarJettax("purchases")}
            className="btn-ghost btn-sm disabled:opacity-50"
          >
            Conferir NF-e recebidas
          </button>
          <button
            type="button"
            disabled={!podeOperar || ocupadoJettax || !jettaxRegistrada(jettax) || !jettaxAtiva}
            onClick={() => importarJettax("sales")}
            className="btn-ghost btn-sm disabled:opacity-50"
          >
            Conferir NF-e emitidas
          </button>
        </div>

        {execucoesJettax.length > 0 && (
          <div className="mt-5 overflow-x-auto">
            <p className="mb-2 text-sm font-medium text-ink">Últimas verificações Jettax</p>
            <table className="tabela">
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Origem</th>
                  <th>Fluxo</th>
                  <th>Status</th>
                  <th className="text-right">Novas</th>
                  <th className="text-right">Duplicadas</th>
                </tr>
              </thead>
              <tbody>
                {execucoesJettax.map((execucao) => (
                  <tr key={execucao.id}>
                    <td className="font-mono text-xs text-ink-muted">{formatarDataHora(execucao.iniciado_em)}</td>
                    <td className="font-mono text-xs text-ink-muted">{execucao.origem}</td>
                    <td>{rotuloFluxoJettax(execucao.fluxo)}</td>
                    <td>
                      <span className={execucao.status === "erro" ? "badge-danger" : execucao.status === "em_andamento" ? "badge-warn" : "badge-ok"}>
                        {execucao.status}
                      </span>
                      {execucao.mensagem_erro && <p className="mt-1 text-xs text-danger">{execucao.mensagem_erro}</p>}
                      {execucao.aviso && <p className="mt-1 text-xs text-ink-muted">{execucao.aviso}</p>}
                    </td>
                    <td className="text-right font-mono text-xs">{execucao.documentos_importados}</td>
                    <td className="text-right font-mono text-xs">{execucao.documentos_duplicados}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card-pad">
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
