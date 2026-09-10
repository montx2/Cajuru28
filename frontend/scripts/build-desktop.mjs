/**
 * Build do painel para o programa instalado (modo desktop).
 *
 * Existe em vez de um `NEXT_BUILD_TARGET=desktop next build` no `package.json`
 * porque essa forma não funciona no `cmd.exe` do Windows — e é justamente no
 * Windows que este build roda. Um script Node resolve sem depender de
 * `cross-env` nem de shell POSIX: aqui o ambiente é montado em JavaScript, que
 * é igual nos dois sistemas.
 *
 * O resultado sai em `out/` (export estático). O empacotador do programa copia
 * essa pasta para dentro do `.exe`.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cli = path.join(raiz, "node_modules", "next", "dist", "bin", "next");

if (!existsSync(cli)) {
  console.error(
    "[build:desktop] Next.js não encontrado em node_modules.\n" +
      "Rode `npm ci` (ou `npm install`) na pasta frontend antes do build."
  );
  process.exit(1);
}

console.log("[build:desktop] Compilando o painel para o programa instalado (export estático)…");

const filho = spawn(process.execPath, [cli, "build"], {
  cwd: raiz,
  stdio: "inherit",
  env: { ...process.env, NEXT_BUILD_TARGET: "desktop" },
});

filho.on("exit", (codigo) => process.exit(codigo ?? 1));
