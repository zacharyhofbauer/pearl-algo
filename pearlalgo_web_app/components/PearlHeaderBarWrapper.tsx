'use client'

import dynamic from 'next/dynamic'

// Dynamic import to avoid SSR issues with WebSocket
const PearlHeaderBar = dynamic(() => import('./PearlHeaderBar'), {
  ssr: false,
})

export default function PearlHeaderBarWrapper() {
  return <PearlHeaderBar />
}
