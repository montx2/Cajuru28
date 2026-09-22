/**
 * Marca da Fluxa: três traços diagonais paralelos e crescentes, sugerindo o
 * fluxo contínuo de documentos fiscais. Vetorial e monocromática — herda
 * `currentColor` para caber em qualquer superfície (sidebar, cartão de
 * vidro, tela de login, favicon).
 *
 * Cada barra é um `<rect>` centrado na origem e rotacionado -32°, depois
 * transladado ao seu centro — evita o rótulo em pixels de um polígono
 * desenhado à mão.
 */
export function LogoFluxa({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} aria-hidden="true">
      <rect x="-12" y="-4.5" width="24" height="9" rx="4.5" fill="currentColor" opacity=".55" transform="translate(34 16) rotate(-32)" />
      <rect x="-16" y="-4.5" width="32" height="9" rx="4.5" fill="currentColor" opacity=".8" transform="translate(31 32) rotate(-32)" />
      <rect x="-21" y="-4.5" width="42" height="9" rx="4.5" fill="currentColor" transform="translate(27 50) rotate(-32)" />
    </svg>
  );
}
