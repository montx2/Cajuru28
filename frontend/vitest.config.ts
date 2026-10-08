import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./", import.meta.url)) } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./testes/setup.ts"], // `.tsx` e `.ts`: a lista antiga só via `.tsx` e deixava test.ts fora da suíte
    // silenciosamente (verde falso no CI).
    include: ["testes/**/*.test.{ts,tsx}"] },
});
