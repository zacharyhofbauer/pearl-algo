import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'PEARL Dashboard',
  description: 'Live trading dashboard for PEARL AI',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
