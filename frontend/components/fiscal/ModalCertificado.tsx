"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dataCurta } from "@/lib/format";
import { mensagemDoErro } from "@/lib/erros";
import { Botao } from "@/components/ui/Botao";
import { CampoArquivo } from "@/components/ui/CampoArquivo";
import { CampoSenha } from "@/components/ui/CampoSenha";
import { Combobox } from "@/components/ui/Combobox";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Icone } from "@/components/ui/Icone";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

export interface OpcaoEmpresaCertificado {
  valor: string;
  rotulo: string;
  descricao?: string;
}

export interface ModalCertificadoProps {
  aberto: boolean;
  aoFechar: () => void;
  /** Chamado após instalar com sucesso, para recarregar a tela de origem. */
  aoInstalar: () => void;
  /**
   * Com `empresas`, o modal pede a empresa (visão da lista de certificados).
   * Sem ele, `empresaId` fixa o destino (visão de detalhe da empresa).
   */
  empresas?: OpcaoEmpresaCertificado[];
  empresaId?: number | null;
}

/**
 * Envio do certificado A1 — o único do sistema.
 *
 * Antes existiam dois modais para esta mesma ação (lista de certificados e
 * detalhe da empresa), com textos e validações diferentes: o da empresa
 * liberava o botão sem senha, deixando o erro estourar só depois do upload.
 * Um componente só elimina a divergência.
 *
 * A senha nunca é persistida em estado global nem devolvida pela API: serve
 * uma vez para abrir o .p12 no servidor e é descartada com o fechamento.
 */
export function ModalCertificado({ aberto, aoFechar, aoInstalar, empresas, empresaId }: ModalCertificadoProps) {
  const { avisar } = useToast();
  const pedeEmpresa = Array.isArray(empresas);
  const [empresa, setEmpresa] = useState(empresaId ? String(empresaId) : "");
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [senha, setSenha] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Reabrir para outra empresa não pode manter a seleção anterior.
  useEffect(() => {
    if (aberto) setEmpresa(empresaId ? String(empresaId) : "");
  }, [aberto, empresaId]);

  const fechar = useCallback(() => {
    setArquivos([]);
    setSenha("");
    setErro(null);
    aoFechar();
  }, [aoFechar]);

  const alvo = pedeEmpresa ? Number(empresa) : (empresaId ?? 0);
  const arquivo = arquivos[0];
  // Mesma regra para as duas visões: sem empresa, arquivo e senha não há envio.
  const podeInstalar = Boolean(alvo) && Boolean(arquivo) && senha.length > 0;

  async function instalar() {
    if (!alvo) {
      setErro("Escolha a empresa que vai receber o certificado.");
      return;
    }
    if (!arquivo) {
      setErro("Selecione o arquivo .p12 ou .pfx.");
      return;
    }
    if (!senha) {
      setErro("Informe a senha do certificado — sem ela o servidor não consegue abrir o arquivo.");
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const criado = await api.enviarCertificado(alvo, senha, arquivo);
      avisar({ tom: "ok", titulo: "Certificado instalado", descricao: `Válido até ${dataCurta(criado.validade)}` });
      aoInstalar();
      fechar();
    } catch (falha) {
      setErro(mensagemDoErro(falha, "instalar o certificado"));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal
      aberto={aberto}
      aoFechar={fechar}
      titulo={pedeEmpresa ? "Enviar certificado A1" : "Certificado A1"}
      descricao="O arquivo é cifrado no servidor. A senha é usada uma vez, para abrir o .p12, e nunca volta ao navegador."
      largura="media"
      rodape={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Botao variante="sutil" onClick={fechar} disabled={enviando}>
            Cancelar
          </Botao>
          <Botao
            variante="primaria"
            onClick={instalar}
            carregando={enviando}
            disabled={!podeInstalar}
            title={podeInstalar ? undefined : pedeEmpresa ? "Preencha empresa, arquivo e senha" : "Selecione o arquivo e informe a senha"}
          >
            Instalar certificado
          </Botao>
        </div>
      }
    >
      <div className="space-y-4">
        {pedeEmpresa ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-tinta">
              Empresa <span className="text-erro">*</span>
            </p>
            <Combobox
              rotulo="Empresa"
              opcoes={empresas ?? []}
              valor={empresa}
              aoMudar={setEmpresa}
              placeholder="Buscar por razão social ou CNPJ"
              vazio="Nenhuma empresa cadastrada"
              permiteLimpar
            />
          </div>
        ) : null}

        <CampoArquivo
          rotulo="Arquivo do certificado"
          obrigatorio
          aceita=".p12,.pfx"
          arquivos={arquivos}
          aoMudar={(lista) => setArquivos(lista.slice(0, 1))}
          descricao={pedeEmpresa ? "Substitui o certificado atual da empresa escolhida." : "Substitui o certificado atual desta empresa."}
        />

        <CampoSenha
          rotulo="Senha do certificado"
          obrigatorio
          autoComplete="off"
          value={senha}
          onChange={(evento) => setSenha(evento.target.value)}
          descricao="Nenhuma tela exibe esta senha depois de enviada."
        />

        {erro ? (
          <p role="alert" className="flex items-start gap-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-sm leading-6 text-erro">
            <Icone nome="alerta" className="mt-1 h-4 w-4 flex-none" />
            <span>{erro}</span>
          </p>
        ) : null}

        {pedeEmpresa && empresa ? (
          <p className="text-xs text-tinta-suave">
            Selecionada: <span className="text-tinta">{empresas?.find((opcao) => opcao.valor === empresa)?.rotulo ?? "—"}</span>
            <Etiqueta tom="neutro" className="ml-2">
              um certificado por empresa
            </Etiqueta>
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
