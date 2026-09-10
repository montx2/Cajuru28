/** @type {import('next').NextConfig} */

/**
 * Dois alvos de build, um código só.
 *
 * - **servidor** (`npm run build`): `output: "standalone"`, servido pelo
 *   contêiner Node. É o modo Docker, com PostgreSQL e Celery.
 * - **desktop** (`npm run build:desktop`): `output: "export"`, um site
 *   estático que o próprio programa Python serve. Sem Node instalado na
 *   máquina do contador, sem uma segunda porta, sem CORS.
 *
 * `trailingSlash: true` no modo desktop é o que faz cada rota virar
 * `caminho/index.html` — formato que o servidor de arquivos estático do
 * backend resolve sem adivinhação.
 */
const modoDesktop = process.env.NEXT_BUILD_TARGET === "desktop";

const nextConfig = modoDesktop
  ? {
      output: "export",
      trailingSlash: true,
      // O export estático não tem o otimizador de imagem do servidor.
      images: { unoptimized: true },
      reactStrictMode: true,
      // Sem isso, o export gera um `404.html` que não sabe lidar com rota de
      // cliente — e um clique no menu depois de um F5 dá 404.
      generateEtags: false,
    }
  : {
      output: "standalone",
      // Aceita qualquer host do preview (sandbox / proxy) — sem isso o Next 16
      // recusa o Host header e a preview quebra.
      allowedDevOrigins: ["*"],
    };

export default nextConfig;
