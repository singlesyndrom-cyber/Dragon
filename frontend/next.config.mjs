/** Сайт ходит в API через /api/* — тот же домен, без CORS и без утечки адреса бэкенда. */
const api = process.env.API_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/:path*` },
      // приложение Android проверяет связь с сайтом по этому адресу (отпечаток ключа - ANDROID_CERT_SHA256 в .env)
      { source: "/.well-known/assetlinks.json", destination: `${api}/app/assetlinks` },
    ];
  },
};

export default nextConfig;
