// @ts-check
const withPWA = require('@ducanh2912/next-pwa').default({
  dest: 'public',
  disable: process.env.NODE_ENV === 'development',
  fallbacks: {
    document: '/~offline',
  },
  extendDefaultRuntimeCaching: true,
  workboxOptions: {
    runtimeCaching: [
      {
        urlPattern: /^https?:\/\/.*\/(api|tv_paper\/api)\//,
        handler: 'NetworkOnly',
        options: { cacheName: 'api-requests' },
      },
      {
        urlPattern: /^https?:\/\/.*\/_next\/static\/.*/,
        handler: 'CacheFirst',
        options: {
          cacheName: 'static-assets',
          expiration: { maxEntries: 64, maxAgeSeconds: 365 * 24 * 60 * 60 },
        },
      },
      {
        urlPattern: /\.(?:png|jpg|jpeg|svg|gif|webp|ico|woff2?)$/,
        handler: 'CacheFirst',
        options: {
          cacheName: 'static-images-fonts',
          expiration: { maxEntries: 64, maxAgeSeconds: 365 * 24 * 60 * 60 },
        },
      },
    ],
  },
})

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,

  // Proxy /tv_paper/* to TV Paper API (8001) so dashboard gets correct state when ?account=tv_paper
  async rewrites() {
    return [
      { source: '/tv_paper/:path*', destination: 'http://127.0.0.1:8001/:path*' },
    ]
  },

  // Disable caching in development for easier debugging
  onDemandEntries: {
    // Keep pages in memory longer (reduces recompilation)
    maxInactiveAge: 60 * 1000,
    // More pages kept in memory
    pagesBufferLength: 5,
  },

  poweredByHeader: false,

  async headers() {
    const securityHeaders = [
      { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
      { key: 'Content-Security-Policy', value: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws: wss: http://localhost:* ws://localhost:*; font-src 'self'; frame-ancestors 'self'" },
      { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
    ]

    if (process.env.NODE_ENV === 'development') {
      return [
        {
          source: '/:path*',
          headers: [
            { key: 'Cache-Control', value: 'no-store, must-revalidate' },
            ...securityHeaders,
          ],
        },
      ]
    }

    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ]
  },
}

module.exports = withPWA(nextConfig)
