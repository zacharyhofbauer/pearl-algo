/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,

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
