/** @type {import('next').NextConfig} */
const nextConfig = {
  // Para desktop, usamos standalone também (não export) porque temos rota dinâmica [id]
  // O Electron vai iniciar o server Next.js standalone em localhost:3000
  output: "standalone",
  images: {
    unoptimized: true,
  },
  // API aponta para backend local no desktop
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },
  // Permitir qualquer host no preview
  allowedDevOrigins: ["*"],
};

export default nextConfig;
