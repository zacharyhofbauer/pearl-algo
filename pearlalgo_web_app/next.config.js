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

module.exports = nextConfig
