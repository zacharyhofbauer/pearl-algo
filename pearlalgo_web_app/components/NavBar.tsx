'use client'

import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'

export default function NavBar() {
  const pathname = usePathname()

  const isHome = pathname === '/' || pathname === ''
  const isDashboard = pathname?.startsWith('/dashboard')
  const isArchive = pathname?.startsWith('/archive')

  return (
    <nav className="nav-bar" role="navigation" aria-label="Main">
      <Link
        href="/"
        className={`nav-bar-brand ${isHome ? 'active' : ''}`}
        aria-label="PEARL Home"
        aria-current={isHome ? 'page' : undefined}
      >
        <Image src="/logo.png" alt="" width={24} height={24} className="nav-bar-logo" />
        <span className="nav-bar-name">PEARL</span>
      </Link>
      <div className="nav-bar-links">
        <Link
          href="/dashboard?account=tv_paper"
          className={`nav-bar-link ${isDashboard ? 'active' : ''}`}
          aria-current={isDashboard ? 'page' : undefined}
        >
          Dashboard
        </Link>
        <Link
          href="/archive/ibkr"
          className={`nav-bar-link ${isArchive ? 'active' : ''}`}
          aria-current={isArchive ? 'page' : undefined}
        >
          Archive
        </Link>
      </div>
    </nav>
  )
}
