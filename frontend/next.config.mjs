/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Permite hosts do proxy de desenvolvimento e da pré-visualização.
  allowedDevOrigins: ["*"],
};

export default nextConfig;
