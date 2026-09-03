/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // Required for react-leaflet (Map container is already initialized)
  typedRoutes: true,

  // Enable standalone output for Docker (disabled on Windows due to symlink
  // issues). NEXT_OUTPUT_STANDALONE=false opts out for builds that will be
  // served by `next start` — which does not work with standalone output
  // (pages serve, but client-side navigation silently breaks) — such as the
  // CI e2e web server.
  output:
    process.platform === 'win32' ||
    process.env.NEXT_OUTPUT_STANDALONE === 'false'
      ? undefined
      : 'standalone',

  // API configuration
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.BACKEND_URL
          ? `${process.env.BACKEND_URL}/api/:path*`
          : 'http://localhost:8001/api/:path*',
      },
    ];
  },

  // Security headers
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
        ],
      },
    ];
  },

  // Image optimization
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: 'localhost',
      },
      {
        protocol: 'https',
        hostname: 'localhost',
      },
    ],
    formats: ['image/webp', 'image/avif'],
  },
};

export default nextConfig;
