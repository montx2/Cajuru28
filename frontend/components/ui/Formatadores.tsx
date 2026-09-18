"use client";
import { useState } from "react";
import { copiarTexto, dataHora, formatarCnpjCpf, moeda, numero, tempoRelativo } from "@/lib/format";
export function ValorMoeda({ valor }: { valor: number | null | undefined }) { return <span className="tabular-nums whitespace-nowrap">{moeda(valor)}</span>; }
export function Quantidade({ valor }: { valor: number | null | undefined }) { return <span className="tabular-nums">{numero(valor)}</span>; }
export function DataHora({ valor }: { valor: string | null | undefined }) { return <time dateTime={valor ?? undefined} title={dataHora(valor)}>{tempoRelativo(valor)}</time>; }
export function CopiavelMono({ valor, exibicao }: { valor: string; exibicao?: string }) { const [copiado, setCopiado] = useState(false); return <span className="inline-flex items-center gap-1 font-mono text-xs"><span>{exibicao ?? valor}</span><button type="button" className="btn-icon h-10 w-10" aria-label={`Copiar ${exibicao ?? valor}`} onClick={async () => { const ok = await copiarTexto(valor); setCopiado(ok); window.setTimeout(() => setCopiado(false), 1600); }}>{copiado ? "✓" : "□"}</button><span className="sr-only" role="status">{copiado ? "Copiado" : ""}</span></span>; }
export function Cnpj({ valor }: { valor: string | null | undefined }) { const texto = formatarCnpjCpf(valor); return valor ? <CopiavelMono valor={valor} exibicao={texto} /> : <span>—</span>; }
