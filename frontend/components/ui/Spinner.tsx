import { cn } from "@/lib/cn";

/**
 * Indicador de trabalho em curso. Sempre decorativo (`aria-hidden`): quem
 * anuncia o estado é o `aria-busy` do controle ou o `role="status"` do bloco.
 */
export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block animate-spin rounded-full border-2 border-current border-r-transparent align-[-2px]",
        className
      )}
    />
  );
}
