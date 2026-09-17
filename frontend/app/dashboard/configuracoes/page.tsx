"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { bytesParaTexto } from "@/lib/competencia";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Esqueleto, TituloSecao } from "@/components/ui";
import type { InfoSistema, ResumoCertificado } from "@/lib/types";

export default function ConfiguracoesPage() {
  const toast = useToast();
  const { ehAdmin } = usePapel();
  const [info, setInfo] = useState<InfoSistema | null>(null);
  const [certificados, setCertificados] = useState<ResumoCertificado[]>([]);
  const [saude, setSaude] = useState<{ problemas: string[]; disco_livre_bytes: number | null } | null>(null);
  const [testando, setTestando] = useState(false);
  const [jettax, setJettax] = useState<{ configurado: boolean; base_url: string; saude: string; mensagem?: string; empresas_registradas: number; empresas_ativas: number } | null>(null);
  const [jettaxToken, setJettaxToken] = useState("");
  const [jettaxUrl, setJettaxUrl] = useState("https://morfeu-api.jettax.com.br");
  const [salvandoJettax, setSalvandoJettax] = useState(false);
  const [acessorias, setAcessorias] = useState<{ configurado: boolean; base_url: string; ultima_sincronizacao_em: string | null } | null>(null);
  const [acessoriasToken, setAcessoriasToken] = useState("");
  const [acessoriasUrl, setAcessoriasUrl] = useState("https://api.acessorias.com");
  const [ocupadoAcessorias, setOcupadoAcessorias] = useState(false);
  const [confirmacaoReset, setConfirmacaoReset] = useState("");
  const [resetando, setResetando] = useState(false);
  const [removerIntegracoesReset, setRemoverIntegracoesReset] = useState(false);
  const [forcarReset, setForcarReset] = useState(false);

  const carregar = useCallback(() => {
    api.infoSistema().then(setInfo).catch(() => setInfo(null));
    api.resumoCertificados().then(setCertificados).catch(() => setCertificados([]));
    api.saudeDetalhada().then(setSaude).catch(() => setSaude(null));
    api.statusJettax().then((r) => { setJettax(r); if (r.base_url) setJettaxUrl(r.base_url); }).catch(() => setJettax(null));
    api.statusAcessorias().then((r) => { setAcessorias(r); if (r.base_url) setAcessoriasUrl(r.base_url); }).catch(() => setAcessorias(null));
  }, []);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, 30_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  async function testarWebhook() {
    setTestando(true);
    try {
      const r = await api.testarWebhook();
      if (r.ok) toast.sucesso("Webhook funcionando — mensagem de teste enviada.");
      else toast.erro(r.detalhe);
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "Falha ao testar o webhook.");
    } finally {
      setTestando(false);
    }
  }

  async function salvarJettax() {
    if (!jettaxToken.trim()) return toast.erro("Informe o token da API Jettax.");
    setSalvandoJettax(true);
    try {
      await api.salvarCredencialJettax(jettaxToken, jettaxUrl);
      setJettaxToken("");
      const teste = await api.testarJettax();
      toast.sucesso(teste.mensagem || "Jettax conectada com sucesso.");
      carregar();
    } catch (e) { toast.erro(e instanceof ApiError ? e.message : "Não foi possível conectar à Jettax."); }
    finally { setSalvandoJettax(false); }
  }

  async function testarJettax() {
    setSalvandoJettax(true);
    try { const r = await api.testarJettax(); toast.sucesso(r.mensagem); carregar(); }
    catch (e) { toast.erro(e instanceof ApiError ? e.message : "Falha no teste da Jettax."); }
    finally { setSalvandoJettax(false); }
  }

  async function salvarAcessorias() {
    if (!acessoriasToken.trim()) return toast.erro("Informe o token da API Acessórias.");
    setOcupadoAcessorias(true);
    try { await api.salvarCredencialAcessorias(acessoriasToken, acessoriasUrl); setAcessoriasToken(""); toast.sucesso("Acessórias conectado com sucesso."); carregar(); }
    catch (e) { toast.erro(e instanceof ApiError ? e.message : "Falha ao conectar ao Acessórias."); }
    finally { setOcupadoAcessorias(false); }
  }

  async function sincronizarAcessorias() {
    setOcupadoAcessorias(true);
    try { const r = await api.sincronizarEmpresasAcessorias(); toast.sucesso(`${r.criadas} empresas cadastradas e ${r.atualizadas} atualizadas.`); carregar(); }
    catch (e) { toast.erro(e instanceof ApiError ? e.message : "Falha ao sincronizar empresas."); }
    finally { setOcupadoAcessorias(false); }
  }

  async function resetarTudo() {
    if (!ehAdmin) return toast.erro("Somente administradores podem limpar o sistema.");
    if (confirmacaoReset.trim().toUpperCase() !== "LIMPAR") {
      return toast.erro("Digite LIMPAR para confirmar a limpeza geral.");
    }
    const ok = window.confirm(
      "Isto apaga empresas, certificados, documentos, XMLs, execuções e cursores do escritório logado. Deseja continuar?"
    );
    if (!ok) return;
    setResetando(true);
    try {
      const r = await api.resetGeral({
        confirmar: "LIMPAR",
        remover_integracoes: removerIntegracoesReset,
        forcar: forcarReset,
      });
      toast.sucesso(`${r.empresas} empresa(s) e ${r.documentos} documento(s) removidos. Sistema pronto para começar do zero.`);
      setConfirmacaoReset("");
      setRemoverIntegracoesReset(false);
      setForcarReset(false);
      carregar();
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "Falha ao limpar o sistema.");
    } finally {
      setResetando(false);
    }
  }

  const vencidos = certificados.filter((item) => item.vencido);
  const vencendo = certificados.filter((item) => item.vence_em_breve && !item.vencido);
  const webhook = info?.webhook;

  return (
    <div className="animate-fade-up max-w-5xl">
      <h1 className="page-title">Configurações</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Diagnóstico do ambiente, certificados, atenção e integrações.
      </p>

      {/* atalhos de gestão */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Link href="/dashboard/atencao" className="card-pad card-hover block">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-warn-soft text-warn">
            <Icone nome="sino" className="h-5 w-5" />
          </span>
          <p className="mt-3 font-semibold text-ink">Atenção</p>
          <p className="mt-0.5 text-xs text-ink-muted">Tudo que precisa de olho humano.</p>
        </Link>
        <Link href="/dashboard/certificados" className="card-pad card-hover block">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent-deep">
            <Icone nome="escudo" className="h-5 w-5" />
          </span>
          <p className="mt-3 font-semibold text-ink">Certificados</p>
          <p className="mt-0.5 text-xs text-ink-muted">Validade e uso de cada A1.</p>
        </Link>
        <Link href="/dashboard/saude" className="card-pad card-hover block">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-info-soft text-info">
            <Icone nome="hd" className="h-5 w-5" />
          </span>
          <p className="mt-3 font-semibold text-ink">Saúde do sistema</p>
          <p className="mt-0.5 text-xs text-ink-muted">Componentes e backup.</p>
        </Link>
        <Link href="/dashboard/auditoria" className="card-pad card-hover block">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-bg text-ink-muted">
            <Icone nome="olho" className="h-5 w-5" />
          </span>
          <p className="mt-3 font-semibold text-ink">Auditoria</p>
          <p className="mt-0.5 text-xs text-ink-muted">Quem fez o quê, quando.</p>
        </Link>
      </div>

      <section className="card-pad mt-4">
        <TituloSecao titulo="Estado dos serviços" />
        {!info || !saude ? (
          <Esqueleto className="h-16" />
        ) : (
          <>
            <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm text-ink-muted">
              <span>
                API:{" "}
                <strong className={saude.problemas.length ? "text-danger" : "text-accent"}>
                  {saude.problemas.length ? "atenção" : "funcionando"}
                </strong>
              </span>
              <span>
                Banco: <strong className="text-ink">{info.banco}</strong>
              </span>
              <span>
                Fila: <strong className="text-ink">{info.fila.modo}</strong>
              </span>
              {saude.disco_livre_bytes != null && (
                <span>
                  Disco livre: <strong className="text-ink">{bytesParaTexto(saude.disco_livre_bytes)}</strong>
                </span>
              )}
            </div>
            {saude.problemas.map((problema) => (
              <p key={problema} className="mt-2 text-sm text-danger">
                {problema}
              </p>
            ))}
          </>
        )}
        <p className="mt-4 text-xs text-ink-muted">
          Atualizações, logs e backups são administrados no servidor com Docker Compose. Proteja os
          volumes <code>db_data</code>, <code>certificados</code> e <code>xml_saida</code>.
        </p>
      </section>

      {ehAdmin && (
        <section className="card-pad mt-4 border border-danger/25 bg-danger-soft/20">
          <TituloSecao
            titulo="Limpar geral / começar do zero"
            subtitulo="Remove empresas, notas, XMLs, certificados, histórico de importação e bloqueios/cooldowns locais do escritório logado."
          />
          <p className="text-sm text-ink-muted">
            Use quando quiser zerar a base para não aparecer nenhuma empresa por padrão. Usuários, auditoria e backups são preservados.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
            <label className="text-xs font-semibold uppercase text-ink-muted">
              Digite LIMPAR para confirmar
              <input
                className="input mt-1 w-full"
                value={confirmacaoReset}
                onChange={(e) => setConfirmacaoReset(e.target.value)}
                placeholder="LIMPAR"
              />
            </label>
            <button
              type="button"
              className="btn-ghost self-end text-danger"
              disabled={resetando || confirmacaoReset.trim().toUpperCase() !== "LIMPAR"}
              onClick={resetarTudo}
            >
              {resetando ? "Limpando…" : "Limpar geral"}
            </button>
          </div>
          <div className="mt-3 space-y-2 text-xs text-ink-muted">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={removerIntegracoesReset}
                onChange={(e) => setRemoverIntegracoesReset(e.target.checked)}
                className="accent-danger"
              />
              remover também tokens/configurações das integrações Acessórias e Jettax
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={forcarReset}
                onChange={(e) => setForcarReset(e.target.checked)}
                className="accent-danger"
              />
              forçar mesmo se houver execução marcada como em andamento
            </label>
          </div>
        </section>
      )}

      <section className="card-pad mt-4">
        <TituloSecao titulo="Sistema Acessórias" subtitulo="Cadastre automaticamente as empresas existentes no Acessórias" />
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <span className={acessorias?.configurado ? "badge-ok" : "badge-neutral"}>{acessorias?.configurado ? "Configurado" : "Não configurado"}</span>
          {acessorias?.ultima_sincronizacao_em && <span className="text-ink-muted">Última sincronização: {new Date(acessorias.ultima_sincronizacao_em).toLocaleString("pt-BR")}</span>}
        </div>
        {ehAdmin && <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label className="text-xs font-semibold text-ink-muted">URL da API
            <input className="input mt-1 w-full" value={acessoriasUrl} onChange={(e) => setAcessoriasUrl(e.target.value)} />
          </label>
          <label className="text-xs font-semibold text-ink-muted">API Token
            <input type="password" autoComplete="new-password" className="input mt-1 w-full" value={acessoriasToken} onChange={(e) => setAcessoriasToken(e.target.value)} placeholder={acessorias?.configurado ? "•••••••• (digite para substituir)" : "Cole o token gerado no Acessórias"} />
          </label>
          <button type="button" className="btn-primary self-end" disabled={ocupadoAcessorias} onClick={salvarAcessorias}>{ocupadoAcessorias ? "Aguarde…" : "Salvar e testar"}</button>
        </div>}
        {ehAdmin && acessorias?.configurado && <button type="button" className="btn-primary mt-4" disabled={ocupadoAcessorias} onClick={sincronizarAcessorias}>{ocupadoAcessorias ? "Sincronizando…" : "Buscar e cadastrar todas as empresas ativas"}</button>}
        <p className="mt-3 text-xs leading-relaxed text-ink-muted">A sincronização consulta <code>/companies/ListAll</code> página por página, compara pelo CNPJ/CPF e evita duplicidades. Empresas existentes recebem razão social, UF e situação atualizadas. O token fica cifrado e não é exibido novamente.</p>
      </section>

      <section className="card-pad mt-4">
        <TituloSecao titulo="Jettax 360" subtitulo="Conecte a API sem editar arquivos do servidor" />
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <span className={jettax?.configurado ? "badge-ok" : "badge-neutral"}>{jettax?.configurado ? "Configurada" : "Não configurada"}</span>
          {jettax?.configurado && <span className="text-ink-muted">{jettax.empresas_registradas} empresas vinculadas · {jettax.empresas_ativas} ativas</span>}
          {jettax?.mensagem && <span className="text-ink-muted">{jettax.mensagem}</span>}
        </div>
        {ehAdmin ? <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label className="text-xs font-semibold text-ink-muted">URL da API
            <input className="input mt-1 w-full" value={jettaxUrl} onChange={(e) => setJettaxUrl(e.target.value)} />
          </label>
          <label className="text-xs font-semibold text-ink-muted">Token da API
            <input type="password" autoComplete="new-password" className="input mt-1 w-full" value={jettaxToken} onChange={(e) => setJettaxToken(e.target.value)} placeholder={jettax?.configurado ? "•••••••• (digite para substituir)" : "Cole o token aqui"} />
          </label>
          <button type="button" className="btn-primary self-end" disabled={salvandoJettax} onClick={salvarJettax}>{salvandoJettax ? "Verificando…" : "Salvar e testar"}</button>
        </div> : <p className="text-sm text-ink-muted">Somente administradores podem alterar a credencial.</p>}
        {ehAdmin && jettax?.configurado && <button type="button" className="btn-ghost btn-sm mt-3" disabled={salvandoJettax} onClick={testarJettax}>Testar conexão novamente</button>}
        <p className="mt-3 text-xs leading-relaxed text-ink-muted">O token é cifrado no cofre do servidor e nunca é exibido novamente. Ele é enviado no header <code>Authorization</code> sem o prefixo &quot;Bearer&quot; (padrão da API Morfeu); ao salvar, o sistema remove automaticamente prefixo, aspas, espaços e quebras de linha. A Jettax mantém dois endereços de API (<code>morfeu-api.jettax.com.br</code> e <code>morfeu.jettax.com.br</code>) e o token só é aceito no ambiente para o qual foi emitido — se o teste recusar a autenticação, experimente o outro endereço no campo URL. As empresas podem ser cadastradas em lote pela tela Empresas e depois vinculadas à Jettax pelo CNPJ.</p>
      </section>

      {/* webhook */}
      <section className="card-pad mt-4">
        <TituloSecao
          titulo="Alertas externos (webhook)"
          subtitulo="Receba os alertas no Slack, Discord ou WhatsApp via gateway"
        />
        <div className="flex flex-wrap items-center gap-3">
          {webhook?.configurado ? (
            <span className="badge-ok">
              <Icone nome="checkCirculo" className="h-3.5 w-3.5" /> Configurado
            </span>
          ) : (
            <span className="badge-neutral">Desligado</span>
          )}
          {webhook?.configurado && (
            <span className="text-xs text-ink-muted">
              a partir de <strong>{webhook.nivel_minimo}</strong> · varredura a cada{" "}
              {webhook.intervalo_minutos} min
            </span>
          )}
          {ehAdmin && (
            <button type="button" onClick={testarWebhook} disabled={testando} className="btn-ghost btn-sm">
              <Icone nome="raio" className="h-4 w-4" />
              {testando ? "Enviando…" : "Enviar teste"}
            </button>
          )}
        </div>
        <p className="mt-3 text-xs leading-relaxed text-ink-muted">
          Configure <code className="font-mono">ALERTA_WEBHOOK_URL</code> no{" "}
          <code className="font-mono">backend/.env</code> com a URL do conector (Slack Incoming
          Webhook, Discord, n8n…) e reinicie os contêineres. O sistema envia cada alerta uma vez e
          respeita o nível mínimo (<code className="font-mono">ALERTA_WEBHOOK_MIN_NIVEL</code>) e o
          cooldown (<code className="font-mono">ALERTA_WEBHOOK_COOLDOWN_MINUTOS</code>).
        </p>
      </section>

      {/* métricas */}
      <section className="card-pad mt-4">
        <TituloSecao titulo="Métricas (Prometheus)" subtitulo="Para monitoramento externo" />
        <p className="text-sm text-ink-muted">
          Endpoint <code className="font-mono text-ink">GET /metricas</code> no formato de exposição
          do Prometheus, autenticado com o mesmo JWT do painel. Aponte o{" "}
          <code className="font-mono">scrape_config</code> para a API com um token de qualquer
          usuário.
        </p>
      </section>

      {/* certificados */}
      <section className="card-pad mt-4">
        <TituloSecao
          titulo="Certificados digitais"
          subtitulo={`${certificados.filter((c) => c.tem_certificado).length} de ${certificados.length} empresas com certificado A1.`}
        />
        {(vencidos.length > 0 || vencendo.length > 0) && (
          <p className="mb-2 text-sm text-warn">Revise certificados vencidos ou próximos do vencimento.</p>
        )}
        <div className="overflow-x-auto">
          <table className="tabela">
            <thead>
              <tr>
                <th>Empresa</th>
                <th>Validade</th>
                <th className="text-right">Situação</th>
              </tr>
            </thead>
            <tbody>
              {certificados.map((certificado) => (
                <tr key={certificado.empresa_id}>
                  <td className="text-ink">{certificado.razao_social}</td>
                  <td className="font-mono text-xs text-ink-muted">
                    {certificado.validade ? certificado.validade.split("-").reverse().join("/") : "—"}
                  </td>
                  <td className="text-right">
                    {!certificado.tem_certificado ? (
                      <span className="badge-neutral">sem certificado</span>
                    ) : certificado.vencido ? (
                      <span className="badge-danger">vencido</span>
                    ) : certificado.vence_em_breve ? (
                      <span className="badge-warn">vence em {certificado.dias_para_vencer} dias</span>
                    ) : (
                      <span className="badge-ok">válido</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!certificados.length && <p className="py-4 text-sm text-ink-muted">Nenhuma empresa cadastrada.</p>}
        </div>
      </section>
    </div>
  );
}
