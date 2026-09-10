/** @type {import('next').NextConfig} */
const ROTAS_API = [
  "auth",
  "empresas",
  "certificados",
  "documentos",
  "importacoes",
  "dashboard",
  "alertas",
  "relatorios",
  "sistema",
];

const nextConfig = {
  output: "standalone",
  // Permite hosts do proxy de desenvolvimento e da pré-visualização.
  allowedDevOrigins: ["*"],
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
    ];
  },
};

export default nextConfig;
