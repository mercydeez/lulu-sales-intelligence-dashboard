// Security headers for the user-facing app (the backend's headers only cover the
// API origin). connect-src is derived from the API URL so fetch + EventSource (SSE)
// keep working. script/style keep 'unsafe-inline' for the Next.js runtime + Tailwind
// (a per-request nonce is the documented next step, which opts pages into dynamic
// rendering); everything else is locked down.
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_URL = API_URL.replace(/^http/, 'ws');
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${API_URL} ${WS_URL}`,
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

const SECURITY_HEADERS = [
  { key: 'Content-Security-Policy', value: CSP },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(self), geolocation=()' },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  swcMinify: true,
  async headers() {
    // In development, drop the CSP: its strict `connect-src` blocks Next's HMR
    // websocket (ws://localhost:3000), which breaks client hydration locally.
    // Production keeps the full CSP. (Mirrors the backend's dev CSP skip.)
    const isDev = process.env.NODE_ENV !== 'production';
    const headers = isDev
      ? SECURITY_HEADERS.filter((h) => h.key !== 'Content-Security-Policy')
      : SECURITY_HEADERS;
    return [{ source: '/:path*', headers }];
  },
  // Reduce chunk size issues
  experimental: {
    optimizePackageImports: ['lucide-react', 'recharts'],
  },
  // Webpack optimizations
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.optimization.splitChunks = {
        chunks: 'all',
        maxSize: 200000,
        cacheGroups: {
          default: false,
          vendors: false,
          // Vendor chunk
          vendor: {
            name: 'vendor',
            chunks: 'all',
            test: /node_modules/,
            priority: 20,
          },
          // Common chunk
          common: {
            name: 'common',
            minChunks: 2,
            chunks: 'all',
            priority: 10,
            reuseExistingChunk: true,
            enforce: true,
          },
        },
      };
    }
    return config;
  },
}

module.exports = nextConfig
