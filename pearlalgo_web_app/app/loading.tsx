import Image from 'next/image'

export default function RootLoading() {
  return (
    <div className="loading-screen" role="status" aria-label="Loading">
      <Image src="/pearl-emoji.png" alt="" className="loading-logo" width={64} height={64} priority />
      <div className="loading-text">Loading...</div>
      <div className="loading-spinner" />
    </div>
  )
}
