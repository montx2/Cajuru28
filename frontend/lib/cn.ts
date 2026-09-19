/**
 * Junção de classes sem dependência: o produto não tem estilo condicional
 * complexo o bastante para justificar `tailwind-merge`, e um utilitário próprio
 * de 10 linhas não cria conflito de especificidade porque cada componente
 * escreve a própria classe uma única vez.
 */
export type ClasseValor = string | number | false | null | undefined | ClasseValor[];

export function cn(...valores: ClasseValor[]): string {
  const saida: string[] = [];
  for (const valor of valores) {
    if (!valor && valor !== 0) continue;
    if (Array.isArray(valor)) {
      const aninhado = cn(...valor);
      if (aninhado) saida.push(aninhado);
      continue;
    }
    saida.push(String(valor));
  }
  return saida.join(" ");
}
