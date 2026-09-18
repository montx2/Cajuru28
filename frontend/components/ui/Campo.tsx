"use client";

import { forwardRef, useId, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Base = { rotulo: string; descricao?: string; erro?: string; className?: string };
export const Entrada = forwardRef<HTMLInputElement, Base & InputHTMLAttributes<HTMLInputElement>>(function Entrada({ rotulo, descricao, erro, className, id, ...props }, ref) {
  const gerado = useId(); const campoId = id ?? gerado; const ajudaId = `${campoId}-ajuda`;
  return <div className={className}><label className="label" htmlFor={campoId}>{rotulo}</label><input ref={ref} id={campoId} className="input" aria-invalid={Boolean(erro)} aria-describedby={descricao || erro ? ajudaId : undefined} {...props} />{(erro || descricao) && <p id={ajudaId} className={cn("mt-1 text-xs", erro ? "text-erro" : "text-tinta-suave")}>{erro ?? descricao}</p>}</div>;
});
export const Area = forwardRef<HTMLTextAreaElement, Base & TextareaHTMLAttributes<HTMLTextAreaElement>>(function Area({ rotulo, descricao, erro, className, id, ...props }, ref) {
  const gerado = useId(); const campoId = id ?? gerado;
  return <div className={className}><label className="label" htmlFor={campoId}>{rotulo}</label><textarea ref={ref} id={campoId} className="input min-h-24" aria-invalid={Boolean(erro)} {...props} />{(erro || descricao) && <p className={cn("mt-1 text-xs", erro ? "text-erro" : "text-tinta-suave")}>{erro ?? descricao}</p>}</div>;
});
export const Selecao = forwardRef<HTMLSelectElement, Base & SelectHTMLAttributes<HTMLSelectElement>>(function Selecao({ rotulo, descricao, erro, className, id, children, ...props }, ref) {
  const gerado = useId(); const campoId = id ?? gerado;
  return <div className={className}><label className="label" htmlFor={campoId}>{rotulo}</label><select ref={ref} id={campoId} className="input" aria-invalid={Boolean(erro)} {...props}>{children}</select>{(erro || descricao) && <p className={cn("mt-1 text-xs", erro ? "text-erro" : "text-tinta-suave")}>{erro ?? descricao}</p>}</div>;
});
