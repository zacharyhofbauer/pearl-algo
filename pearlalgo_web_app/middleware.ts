import { NextResponse } from 'next/server'

/**
 * Middleware - currently a no-op passthrough.
 * Auth was removed. This file is kept for future middleware needs
 * (rate limiting, headers, etc.).
 */
export function middleware() {
  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next).*)'],
}
