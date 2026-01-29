import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'PEARL Live Main Chart',
  description: 'Live TradingView chart for PEARL AI trading',
  icons: {
    icon: '/logo.png',
    shortcut: '/logo.png',
    apple: '/logo.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body>{children}</body>
    </html>
  )
}
