"use client";

import { useEffect, useState } from "react";

/**
 * "⌘K" no macOS, "Ctrl K" no resto. Descoberto no cliente: o servidor não sabe
 * qual é o sistema do operador e um rótulo errado ensina atalho que não existe.
 */
export function useTeclaModificadora(): { simbolo: string; nome: string; ehMac: boolean } {
  const [ehMac, setEhMac] = useState(false);

  useEffect(() => {
    setEhMac(/mac|iphone|ipad|ipod/i.test(navigator.userAgent));
  }, []);

  return ehMac ? { simbolo: "⌘", nome: "Command", ehMac } : { simbolo: "Ctrl", nome: "Control", ehMac };
}
