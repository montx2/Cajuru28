/** @type {import('next').NextConfig} */
const ROTAS_API = [
  "auth",
  "empresas",
  "certificados",
  "documentos",
  "importacoes",
  "dashboard",
  "painel",
  "alertas",
  "relatorios",
  "sistema",
  "usuarios",
  "auditoria",
  // Jettax/Morfeu e Acessórias (Configurações e detalhe da empresa).
  "integracoes",
];

const nextConfig = {
  output: "standalone",
  // Next só aceita hosts de desenvolvimento explicitamente autorizados. Em
  // preview informe NEXT_ALLOWED_DEV_ORIGINS=host-do-preview; produção não
  // aceita wildcard de origem para o canal de desenvolvimento.
  allowedDevOrigins: (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
    .split(",")
    .map((origem) => origem.trim())
    .filter(Boolean),
  async rewrites() {
    // Preview local sem Docker: com PREVIEW_PROXY=1 o próprio Next
    // encaminha as chamadas da API ao backend, então o navegador só fala
    // com um host (e NEXT_PUBLIC_API_URL pode ficar vazio).
    if (process.env.PREVIEW_PROXY !== "1") return [];
    const destino = process.env.PREVIEW_API ?? "http://127.0.0.1:8000";
    return [
      ...ROTAS_API.map((rota) => ({
        source: `/${rota}/:path*`,
        destination: `${destino}/${rota}/:path*`,
      })),
      { source: "/saude", destination: `${destino}/saude` },
      { source: "/metricas", destination: `${destino}/metricas` },
    ];
  },
};

export default nextConfig;
