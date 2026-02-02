import type { Metadata, Viewport } from 'next'
import './globals.css'
import PearlHeaderBarWrapper from '@/components/PearlHeaderBarWrapper'

export const metadata: Metadata = {
  title: 'Pearl Algo Web App',
  description: 'Pearl Algo trading dashboard and monitoring',
  manifest: '/manifest.json',
  icons: {
    icon: '/logo.png',
    shortcut: '/logo.png',
    apple: [
      { url: '/apple-icon-180-v4.png', sizes: '180x180', type: 'image/png' },
    ],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black',
    title: 'PEARL',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#0a0a0f',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <link rel="apple-touch-icon" href="/apple-icon-v4.png" />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-icon-180-v4.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black" />
        <meta name="apple-mobile-web-app-title" content="PEARL" />
      </head>
      <body>
        <PearlHeaderBarWrapper />
        <div className="main-content">{children}</div>
      </body>
    </html>
  )
}
