/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Aceita qualquer host do preview (sandbox / proxy) — sem isso o Next 16
  // recusa o Host header e a preview quebra.
  allowedDevOrigins: ["*"],
};

export default nextConfig;
