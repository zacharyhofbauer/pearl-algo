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

  // Add cache-busting headers in development
  async headers() {
    if (process.env.NODE_ENV === 'development') {
      return [
        {
          source: '/:path*',
          headers: [
            { key: 'Cache-Control', value: 'no-store, must-revalidate' },
          ],
        },
      ]
    }
    return []
  },
}

module.exports = nextConfig
