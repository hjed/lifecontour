/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable experimental features
  experimental: {
    // Enable TypeScript plugin
    typedRoutes: true,
  },

  // Transpile packages from workspace
  transpilePackages: ['@personal-management/shared'],

  // Environment variables
  env: {
    CUSTOM_KEY: process.env.CUSTOM_KEY,
  },

  // Image optimization
  images: {
    domains: [
      'localhost',
      // Add Immich domain when we integrate
    ],
    formats: ['image/webp', 'image/avif'],
  },

  // Internationalization for Australian locale
  i18n: {
    locales: ['en-AU'],
    defaultLocale: 'en-AU',
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

  // Redirects
  async redirects() {
    return [
      {
        source: '/',
        destination: '/dashboard',
        permanent: false,
      },
    ];
  },

  // API rewrites for development
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:3001/api/v1/:path*',
      },
    ];
  },

  // Webpack configuration
  webpack: (config, { buildId, dev, isServer, defaultLoaders, webpack }) => {
    // Add custom webpack configurations here if needed
    return config;
  },

  // Output configuration for Docker (disabled for Windows development)
  // output: 'standalone',

  // Disable powered by header
  poweredByHeader: false,

  // Compression
  compress: true,

  // Development configuration
  ...(process.env.NODE_ENV === 'development' && {
    // Enable React strict mode in development
    reactStrictMode: true,

    // Enable SWC minification
    swcMinify: true,
  }),
};

module.exports = nextConfig;
