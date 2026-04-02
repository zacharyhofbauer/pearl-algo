import Image from 'next/image'
import Link from 'next/link'

export default function NotFound() {
  return (
    <main className="not-found-page">
      <Image
        src="/pearl-emoji.png"
        alt=""
        width={64}
        height={64}
        className="not-found-icon"
      />
      <h1 className="not-found-title">404</h1>
      <p className="not-found-message">This page does not exist.</p>
      <Link href="/" className="not-found-link">
        Back to Home
      </Link>
    </main>
  )
}
