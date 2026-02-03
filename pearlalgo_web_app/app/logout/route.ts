import { NextResponse } from 'next/server'

const COOKIE_NAME = 'pearl_webapp_auth'

export async function GET(request: Request) {
  const url = new URL('/login', request.url)
  const res = NextResponse.redirect(url)
  res.cookies.set(COOKIE_NAME, '', { path: '/', expires: new Date(0) })
  return res
}

