import { NextResponse, type NextRequest } from 'next/server'

const COOKIE_NAME = 'pearl_webapp_auth'

function isAuthEnabled(): boolean {
  return (process.env.PEARL_WEBAPP_AUTH_ENABLED || 'false').toLowerCase() === 'true'
}

function getPasscode(): string {
  return process.env.PEARL_WEBAPP_PASSCODE || ''
}

function isBypassedPath(pathname: string): boolean {
  // Public endpoints/pages (no auth required)
  if (pathname === '/login' || pathname === '/logout') return true

  // Next.js internals + static assets
  if (pathname.startsWith('/_next')) return true
  if (pathname.startsWith('/favicon')) return true

  // Any file-like path (e.g. .png, .js, .css, manifest.json)
  if (pathname.includes('.')) return true

  return false
}

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function middleware(request: NextRequest) {
  if (!isAuthEnabled()) return NextResponse.next()

  const { pathname } = request.nextUrl
  if (isBypassedPath(pathname)) return NextResponse.next()

  const passcode = getPasscode()
  if (!passcode) {
    return new NextResponse('Web app auth enabled but PEARL_WEBAPP_PASSCODE is not set.', {
      status: 503,
      headers: { 'content-type': 'text/plain; charset=utf-8' },
    })
  }

  const cookie = request.cookies.get(COOKIE_NAME)?.value || ''
  const expected = await sha256Hex(passcode)

  if (cookie !== expected) {
    const loginUrl = request.nextUrl.clone()
    loginUrl.pathname = '/login'
    loginUrl.searchParams.set('next', pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next).*)'],
}

