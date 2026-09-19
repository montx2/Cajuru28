"use client";

import { useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { bytesParaTexto } from "@/lib/format";
import { Campo, type CampoBase } from "./Campo";
import { Icone } from "./Icone";

const LIMITE_PADRAO = 35 * 1024 * 1024; // 35 MiB — o teto que a API responde com 413.

export interface CampoArquivoProps extends CampoBase {
  aceita: string;
  multiplo?: boolean;
  arquivos: File[];
  aoMudar: (arquivos: File[]) => void;
  maxBytes?: number;
  textoArraste?: string;
  id?: string;
}

/**
 * Envio de arquivo com arrastar-e-soltar **e** botão.
 *
 * Arrastar é atalho, nunca o único caminho (WCAG 2.5.7): quem usa teclado ou
 * switch control precisa do seletor. A validação de extensão e tamanho acontece
 * antes do envio, com o motivo por arquivo — descobrir no 413 da API custa um
 * novo upload de 30 certificados.
 */
export function CampoArquivo({ rotulo, descricao, erro, nota, obrigatorio, acaoRotulo, className, aceita, multiplo, arquivos, aoMudar, maxBytes = LIMITE_PADRAO, textoArraste, id }: CampoArquivoProps) {
  const gerado = useId();
  const campoId = id ?? gerado;
  const entrada = useRef<HTMLInputElement | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const [recusados, setRecusados] = useState<string[]>([]);

  const extensoes = aceita.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);

  function receber(lista: FileList | null) {
    if (!lista) return;
    const novos: File[] = [];
    const problemas: string[] = [];
    for (const arquivo of Array.from(lista)) {
      const nome = arquivo.name.toLowerCase();
      if (extensoes.length && !extensoes.some((extensao) => nome.endsWith(extensao))) {
        problemas.push(`${arquivo.name}: extensão fora do aceito (${aceita}).`);
        continue;
      }
      if (arquivo.size > maxBytes) {
        problemas.push(`${arquivo.name}: ${bytesParaTexto(arquivo.size)}, acima do limite de ${bytesParaTexto(maxBytes)}.`);
        continue;
      }
      if (!multiplo && novos.length + arquivos.length >= 1) {
        novos.length = 0;
        aoMudar([arquivo]);
        setRecusados(problemas);
        return;
      }
      novos.push(arquivo);
    }
    setRecusados(problemas);
    aoMudar(multiplo ? [...arquivos, ...novos] : novos.slice(0, 1));
    if (entrada.current) entrada.current.value = "";
  }

  return (
    <Campo rotulo={rotulo} descricao={descricao} erro={erro} nota={nota} obrigatorio={obrigatorio} acaoRotulo={acaoRotulo} className={className} id={campoId}>
      {(idCampo) => (
        <div className="space-y-2">
          <div
            onDragOver={(evento) => {
              evento.preventDefault();
              setArrastando(true);
            }}
            onDragLeave={() => setArrastando(false)}
            onDrop={(evento) => {
              evento.preventDefault();
              setArrastando(false);
              receber(evento.dataTransfer.files);
            }}
            className={cn(
              "flex flex-col items-center justify-center gap-2 rounded-cartao border border-dashed px-4 py-6 text-center transition-colors duration-120",
              arrastando ? "border-acento bg-acento-tenue" : "border-borda-controle bg-fundo-afundado"
            )}
          >
            <Icone nome="enviar" className="h-5 w-5 text-tinta-suave" />
            <p className="text-sm text-tinta">
              {textoArraste ?? `Arraste ${multiplo ? "os arquivos" : "o arquivo"} aqui (${aceita})`}
            </p>
            <button
              type="button"
              onClick={() => entrada.current?.click()}
              className="rounded-controle border border-borda-controle bg-superficie px-3 py-1.5 text-sm font-medium text-tinta transition-colors duration-120 hover:bg-fundo-afundado"
            >
              Selecionar {multiplo ? "arquivos" : "arquivo"}
            </button>
            <input
              id={idCampo}
              ref={entrada}
              type="file"
              accept={aceita}
              multiple={multiplo}
              onChange={(evento) => receber(evento.target.files)}
              className="sr-only"
            />
          </div>

          {arquivos.length ? (
            <ul className="divide-y divide-traco rounded-controle border border-traco">
              {arquivos.map((arquivo) => (
                <li key={`${arquivo.name}-${arquivo.size}`} className="flex items-center gap-2 px-2.5 py-1.5 text-sm">
                  <Icone nome="documento" className="h-4 w-4 flex-none text-tinta-suave" />
                  <span className="min-w-0 flex-1 truncate" title={arquivo.name}>
                    {arquivo.name}
                  </span>
                  <span className="nums flex-none text-xs text-tinta-suave">{bytesParaTexto(arquivo.size)}</span>
                  <button
                    type="button"
                    aria-label={`Remover ${arquivo.name}`}
                    onClick={() => aoMudar(arquivos.filter((item) => item !== arquivo))}
                    className="flex h-7 w-7 flex-none items-center justify-center rounded-badge text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-erro"
                  >
                    <Icone nome="fechar" className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {recusados.length ? (
            <ul role="alert" className="space-y-1 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2 text-xs text-erro">
              {recusados.map((mensagem) => (
                <li key={mensagem}>{mensagem}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </Campo>
  );
}
