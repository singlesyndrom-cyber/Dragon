/** Сайт ходит в API через /api/* — тот же домен, без CORS и без утечки адреса бэкенда. */
const api = process.env.API_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
