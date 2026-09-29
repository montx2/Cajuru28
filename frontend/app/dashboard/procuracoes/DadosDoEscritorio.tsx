"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useRecurso } from "@/lib/useRecurso";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { Entrada } from "@/components/ui/Campo";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

interface Props {
  aberta: boolean;
  aoFechar: () => void;
  /**
   * A aba é aberta no clique de continuação, antes da ida à API, para que o
   * navegador não a trate como pop-up. Quem chamou continua o mesmo fluxo
   * direto e fecha a aba se a criação do job falhar.
   */
  aoSalvar: (abaDaReceita: Window | null) => void;
}

/**
 * Primeira pergunta do modo simples.
 *
 * O CNPJ/CPF da contabilidade é o único dado que o sistema não pode deduzir:
 * ele define juridicamente quem receberá a autorização. Esta tela guarda esse
 * dado uma vez, sem expor a configuração administrativa, estações, PFX ou
 * senhas para quem só quer começar uma procuração.
 */
export function DadosDoEscritorio({ aberta, aoFechar, aoSalvar }: Props) {
  const { ehAdmin, somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const [documento, setDocumento] = useState("");
  const [nome, setNome] = useState("");
  const [salvando, setSalvando] = useState(false);
  const configuracao = useRecurso(
    () => (aberta ? api.configuracaoProcuracoes() : Promise.resolve(null)),
    [aberta]
  );

  useEffect(() => {
    if (!configuracao.dados) return;
    setDocumento(configuracao.dados.outorgado_documento || "");
    setNome(configuracao.dados.outorgado_nome || "");
  }, [configuracao.dados]);

  async function salvarEContinuar() {
    if (!configuracao.dados || !documento.trim() || somenteLeitura || !ehAdmin) return;

    // Mantém a ativação de usuário: depois de um `await`, alguns navegadores
    // bloqueiam `window.open`. A Receita só recebe a URL oficial mais adiante.
    const abaDaReceita = typeof window === "undefined" ? null : window.open("", "_blank");
    setSalvando(true);
    try {
      await api.salvarConfiguracaoProcuracoes({
        ...configuracao.dados,
        outorgado_documento: documento.trim(),
        outorgado_nome: nome.trim(),
      });
      avisar({ tom: "ok", titulo: "Dados do escritório salvos", descricao: "Eles serão usados nas próximas procurações deste escritório." });
      aoSalvar(abaDaReceita);
    } catch (erro) {
      abaDaReceita?.close();
      avisar({ tom: "erro", titulo: "Não foi possível salvar os dados do escritório", descricao: mensagemDoErro(erro, "salvar os dados do escritório") });
    } finally {
      setSalvando(false);
    }
  }

  const podeSalvar = Boolean(documento.trim()) && !salvando && !somenteLeitura && ehAdmin;

  return (
    <Modal
      aberto={aberta}
      aoFechar={aoFechar}
      titulo="Antes de começar"
      descricao="Informe uma única vez para qual contabilidade a empresa dará acesso."
      rodape={
        <>
          <Botao variante="sutil" onClick={aoFechar} disabled={salvando}>
            Agora não
          </Botao>
          {ehAdmin ? (
            <Botao
              variante="primaria"
              carregando={salvando}
              disabled={!podeSalvar}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : !documento.trim() ? "Informe o CNPJ ou CPF da contabilidade" : undefined}
              onClick={salvarEContinuar}
            >
              Salvar e começar
            </Botao>
          ) : null}
        </>
      }
    >
      {configuracao.carregando ? <p className="text-sm text-tinta-suave">Carregando…</p> : null}
      {configuracao.erro ? <Aviso tom="erro" titulo="Não foi possível preparar a procuração">{mensagemDoErro(configuracao.erro)}</Aviso> : null}

      {configuracao.dados ? (
        <div className="space-y-4">
          <p className="text-sm leading-6 text-tinta-suave">
            Este é o CNPJ/CPF que aparecerá como recebedor da autorização no Portal da Receita. Não é o dado do cliente, nem uma senha ou certificado.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Entrada
              rotulo="CNPJ/CPF da sua contabilidade"
              obrigatorio
              value={documento}
              onChange={(evento) => setDocumento(evento.target.value)}
              disabled={somenteLeitura || !ehAdmin || salvando}
              placeholder="Somente números ou com pontuação"
              inputMode="numeric"
              autoComplete="off"
              mono
            />
            <Entrada
              rotulo="Nome da sua contabilidade"
              value={nome}
              onChange={(evento) => setNome(evento.target.value)}
              disabled={somenteLeitura || !ehAdmin || salvando}
              placeholder="Ex.: Contabilidade Exemplo Ltda."
              autoComplete="organization"
            />
          </div>
          {!ehAdmin ? (
            <Aviso tom="espera" icone="cadeado" titulo="Peça ao administrador do escritório">
              Só um administrador pode informar esta identidade jurídica uma vez. Depois disso, você poderá iniciar a procuração normalmente.
            </Aviso>
          ) : null}
          <Aviso tom="info" icone="cadeado" titulo="Sem certificados ou senhas aqui">
            O certificado continua no Windows e a confirmação continua no Portal da Receita. Este painel não recebe PFX, senha ou sessão do portal.
          </Aviso>
        </div>
      ) : null}
    </Modal>
  );
}
