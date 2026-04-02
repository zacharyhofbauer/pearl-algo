import Image from 'next/image'

export default function DashboardLoading() {
  return (
    <div className="loading-screen" role="status" aria-label="Loading dashboard">
      <Image src="/pearl-emoji.png" alt="" className="loading-logo" width={64} height={64} priority />
      <div className="loading-text">Loading Dashboard...</div>
      <div className="loading-spinner" />
    </div>
  )
}
