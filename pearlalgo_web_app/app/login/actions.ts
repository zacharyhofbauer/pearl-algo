'use server'

import crypto from 'crypto'
import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

const COOKIE_NAME = 'pearl_webapp_auth'

function isAuthEnabled(): boolean {
  return (process.env.PEARL_WEBAPP_AUTH_ENABLED || 'true').toLowerCase() === 'true'
}

function sha256Hex(value: string): string {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex')
}

export async function login(formData: FormData): Promise<void> {
  const nextRaw = String(formData.get('next') || '/')
  const next = nextRaw.startsWith('/') ? nextRaw : '/'
  const passcode = String(formData.get('passcode') || '').trim()

  if (!isAuthEnabled()) {
    redirect(next || '/')
  }

  const expectedPasscode = process.env.PEARL_WEBAPP_PASSCODE || ''
  if (!expectedPasscode) {
    redirect('/login?error=misconfigured')
  }

  if (passcode !== expectedPasscode) {
    redirect(`/login?error=invalid&next=${encodeURIComponent(next || '/')}`)
  }

  const token = sha256Hex(expectedPasscode)
  // Session TTL: 7 days (configurable via env). Prevents indefinite sessions.
  const sessionTtlHours = parseInt(process.env.PEARL_WEBAPP_SESSION_TTL_HOURS || '168', 10)
  const maxAgeSeconds = sessionTtlHours * 60 * 60
  cookies().set(COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: maxAgeSeconds,
  })

  redirect(next || '/')
}

