"use client";

import { mesAtual } from "@/lib/competencia";
import { SeletorMes } from "@/components/fiscal/SeletorMes";
import { useContextoGlobal } from "./ProvedorContexto";

/**
 * Competência no cabeçalho: o mês de trabalho do sistema inteiro, sempre à
 * vista em qualquer tela.
 *
 * É a única peça de contexto global que subiu para o cabeçalho. Empresa não
 * subiu junto de propósito: "qual empresa" muda de tela para tela (a lista de
 * empresas, o certificado, a importação e o acervo têm cada um o seu recorte),
 * e um seletor único no topo só criava um filtro invisível que o operador não
 * conseguia relacionar com o que estava vendo. "Qual mês" é sempre a mesma
 * pergunta, e a resposta vale para tudo.
 */
export function SeletorCompetencia() {
  const { mes, pronto, definirMes } = useContextoGlobal();
  return (
    <SeletorMes compacto rotulo="Competência" value={pronto ? mes : ""} max={mesAtual()} onChange={definirMes} />
  );
}
