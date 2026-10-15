"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { useRecurso } from "@/lib/useRecurso";
import { Cartao } from "@/components/ui/Cartao";
import { Entrada, Selecao } from "@/components/ui/Campo";
import { Botao } from "@/components/ui/Botao";
import { Aviso } from "@/components/ui/Aviso";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { useToast } from "@/components/ui/Toast";

const ROTULOS = {
  pendente: "Na fila", em_andamento: "Importando", concluida: "Concluída",
  parcial: "Parcial — conferir", erro: "Erro", ignorada: "Empresa não cadastrada no Jettax",
};

export function JettaxIntegracao({ admin, somenteLeitura }: { admin: boolean; somenteLeitura: boolean }) {
  const status = useRecurso(() => api.statusJettax());
  const empresas = useRecurso(() => api.listarEmpresas());
  const execucoes = useRecurso(() => api.execucoesJettax());
  const [token, setToken] = useState("");
  const [competencia, setCompetencia] = useState("");
  const [empresa, setEmpresa] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const { avisar } = useToast();
  const rodando = execucoes.dados?.some((item) => item.status === "pendente" || item.status === "em_andamento");
  const atualizarExecucoes = execucoes.atualizar;

  useEffect(() => {
    if (!rodando) return;
    const timer = window.setInterval(atualizarExecucoes, 5000);
    return () => window.clearInterval(timer);
  }, [rodando, atualizarExecucoes]);

  async function executar(acao: () => Promise<void>) {
    setOcupado(true);
    try {
      await acao();
      status.atualizar();
      execucoes.atualizar();
    } catch (erro) {
      avisar({ tom: "erro", titulo: "A ação Jettax não foi concluída", descricao: mensagemDoErro(erro, "comunicar com o Jettax") });
    } finally {
      setOcupado(false);
    }
  }

  const ativas = empresas.dados?.filter((item) => item.ativa) ?? [];
  const ids = empresa === "todas" ? ativas.map((item) => item.id) : empresa ? [Number(empresa)] : [];
  const podeImportar = !somenteLeitura && !!status.dados?.configurado && !!competencia.trim() && ids.length > 0 && ids.length <= 30;
  const motivoImportar = somenteLeitura ? "Seu perfil permite somente leitura." : !status.dados?.configurado ? "Salve primeiro o token Jettax." : ids.length > 30 ? "Selecione até 30 empresas por pedido." : "Selecione empresa e competência. Apenas NFS-e; NFe e CT-e não serão consultados.";

  return (
    <Cartao titulo="Jettax Morfeu 360" descricao="Importação de NFS-e por competência, sem certificado local e sem alterar o cadastro no Jettax">
      <div className="space-y-4">
        <Aviso tom="info" titulo="Somente NFS-e nesta etapa">
          Os XMLs são baixados imediatamente e o token fica cifrado por escritório. Esta ação não liga nem desliga a captura atual de NFe/CT-e.
          Não mantenha dois coletores de NFe/CT-e usando o mesmo certificado: há risco de bloqueio 656.
        </Aviso>
        {status.carregando ? <EsqueletoBloco linhas={2} /> : status.erro ? (
          <EstadoErro erro={status.erro} aoTentarNovamente={status.atualizar} contexto="ler a integração Jettax" />
        ) : (
          <p className="text-sm">{status.dados?.configurado ? "Token configurado no cofre." : "Token ainda não configurado."} API: {status.dados?.base_url}</p>
        )}
        <Entrada rotulo="Token Jettax" type="password" autoComplete="off" value={token}
          onChange={(evento) => setToken(evento.target.value)} disabled={!admin || somenteLeitura || ocupado}
          descricao="Somente administrador pode salvar ou remover. O token atual nunca é exibido." />
        <div className="flex flex-wrap gap-2">
          <Botao variante="secundaria" disabled={!admin || somenteLeitura || ocupado || !token.trim()}
            title={!admin ? "Somente administrador salva credenciais." : "Validar e cifrar o token no servidor"}
            onClick={() => executar(async () => {
              try { await api.salvarCredencialJettax(token); }
              finally { setToken(""); }
              avisar({ tom: "ok", titulo: "Token Jettax salvo no cofre" });
            })}>Salvar token Jettax</Botao>
          <Botao variante="sutil" disabled={!admin || somenteLeitura || ocupado || !status.dados?.configurado}
            title="Somente administrador testa a credencial salva"
            onClick={() => executar(async () => {
              const resposta = await api.testarJettax();
              avisar({ tom: "ok", titulo: resposta.mensagem });
            })}>Testar conexão Jettax</Botao>
          <Botao variante="sutil" disabled={!admin || somenteLeitura || ocupado || !status.dados?.configurado}
            title="Remove somente o token local; não apaga notas nem modifica o Jettax"
            onClick={() => {
              if (window.confirm("Remover o token Jettax deste escritório? Notas já importadas serão mantidas.")) {
                executar(async () => { await api.removerCredencialJettax(); setToken(""); });
              }
            }}>Remover token Jettax</Botao>
        </div>
        {empresas.erro ? <EstadoErro erro={empresas.erro} aoTentarNovamente={empresas.atualizar} contexto="listar empresas para o Jettax" /> : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <Selecao rotulo="Empresa para importar" value={empresa} onChange={(evento) => setEmpresa(evento.target.value)}
            disabled={somenteLeitura || ocupado || empresas.carregando}
            opcoes={[
              { valor: "", rotulo: "Selecione uma empresa" },
              ...(ativas.length > 0 && ativas.length <= 30 ? [{ valor: "todas", rotulo: "Todas as empresas ativas (até 30)" }] : []),
              ...ativas.map((item) => ({ valor: String(item.id), rotulo: item.razao_social })),
            ]} />
          <Entrada rotulo="Competência Jettax" placeholder="10/2026" value={competencia}
            onChange={(evento) => setCompetencia(evento.target.value)} disabled={somenteLeitura || ocupado}
            descricao="Informe o mês desejado. Emitidas e recebidas serão consultadas." />
        </div>
        <Botao disabled={!podeImportar || ocupado} carregando={ocupado} title={motivoImportar}
          onClick={() => executar(async () => {
            const novas = await api.importarJettax(ids, competencia);
            execucoes.definir(novas);
            avisar({ tom: novas.some((item) => item.status === "erro") ? "espera" : "ok", titulo: "Pedido Jettax registrado", descricao: "Acompanhe cada empresa abaixo. O processamento ocorre no worker." });
          })}>Importar do Jettax</Botao>
        <div className="border-t border-traco pt-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium">Últimas importações Jettax</h3>
            <Botao variante="sutil" tamanho="sm" onClick={() => execucoes.atualizar()}>Atualizar importações Jettax</Botao>
          </div>
          {execucoes.erro ? <EstadoErro erro={execucoes.erro} aoTentarNovamente={execucoes.atualizar} contexto="acompanhar importações Jettax" /> : null}
          {!execucoes.carregando && !execucoes.erro && !execucoes.dados?.length ? <p className="text-sm text-tinta-suave">Nenhuma importação Jettax registrada.</p> : null}
          <ul className="space-y-3" aria-live="polite">
            {execucoes.dados?.map((item) => (
              <li key={item.id} className="rounded-controle border border-traco p-3 text-sm">
                <p className="font-medium">{item.empresa_nome} · {item.competencia} · {ROTULOS[item.status]}</p>
                <p>{item.resultado.recebidos ?? 0} arquivos recebidos · {item.resultado.importados ?? 0} cópias importadas · {item.resultado.duplicados ?? 0} duplicadas · {item.resultado.cancelados ?? 0} canceladas · {item.resultado.erros ?? 0} erros · {item.resultado.sem_empresa ?? 0} sem empresa correspondente</p>
                {Object.entries(item.resultado.motivos_erros ?? {}).map(([motivo, quantidade]) => (
                  <p key={motivo} className="mt-1 text-tinta-suave">{quantidade} ocorrência(s): {motivo}</p>
                ))}
                {item.mensagem ? <p className="mt-1 text-tinta-suave">{item.mensagem}</p> : null}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-tinta-suave">Reexecutar não duplica notas. A Jettax pode demorar até 48 horas para disponibilizar NFS-e; notas anteriores à configuração ou competência inicial podem não estar disponíveis. Uma consulta concluída não comprova que a origem capturou todas as notas.</p>
        </div>
      </div>
    </Cartao>
  );
}
