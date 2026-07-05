/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Served at telos.nousergon.ai/dash via Cloudflare Worker → EC2 origin.
  basePath: "/dash",
};

export default nextConfig;
