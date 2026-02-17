import type { Metadata, Viewport } from 'next'
import './globals.css'
import NavBar from '@/components/NavBar'

export const metadata: Metadata = {
  metadataBase: new URL('https://pearlalgo.io'),
  title: 'PEARL Algo — Algorithmic Trading Dashboard',
  description: 'Live algorithmic trading on MNQ futures. Real-time charts, trade analytics, and performance tracking. Built with transparency.',
  manifest: '/manifest.json',
  icons: {
    icon: '/logo.png',
    shortcut: '/logo.png',
    apple: [
      { url: '/apple-icon-180-v4.png', sizes: '180x180', type: 'image/png' },
    ],
  },
  openGraph: {
    title: 'PEARL Algo — Algorithmic Trading Dashboard',
    description: 'Live algorithmic trading on MNQ futures. Real-time charts, trade analytics, and performance tracking.',
    url: 'https://pearlalgo.io',
    siteName: 'PEARL Algo',
    images: [
      {
        url: '/pearl-emoji.png',
        width: 512,
        height: 512,
        alt: 'PEARL Algo',
      },
    ],
    locale: 'en_US',
    type: 'website',
  },
  twitter: {
    card: 'summary',
    title: 'PEARL Algo — Algorithmic Trading Dashboard',
    description: 'Live algorithmic trading on MNQ futures. Real-time charts, trade analytics, and performance tracking.',
    images: ['/pearl-emoji.png'],
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
        <noscript>
          <div style={{
            position: 'fixed',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#0a0a0f',
            color: '#b0b8c8',
            fontFamily: 'system-ui, sans-serif',
            padding: 24,
            textAlign: 'center',
          }}>
            <p>Pearl Algo Dashboard requires JavaScript. Please enable it and reload.</p>
          </div>
        </noscript>
        <NavBar />
        {children}
      </body>
    </html>
  )
}
