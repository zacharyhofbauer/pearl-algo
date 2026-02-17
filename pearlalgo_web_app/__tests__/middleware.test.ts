/**
 * @jest-environment node
 */
import crypto from 'crypto'
import { NextRequest } from 'next/server'
import { middleware, config } from '@/middleware'

const originalEnv = process.env

/** Compute SHA-256 hex using Node crypto (mirrors the middleware sha256Hex) */
function sha256Hex(input: string): string {
  return crypto.createHash('sha256').update(input, 'utf8').digest('hex')
}

/** Create a NextRequest for the given path, optionally with an auth cookie */
function createRequest(path: string, cookie?: string): NextRequest {
  const req = new NextRequest(new URL(path, 'http://localhost:3001'))
  if (cookie !== undefined) {
    req.cookies.set('pearl_webapp_auth', cookie)
  }
  return req
}

/** Check if the response is a pass-through (NextResponse.next()) */
function isPassThrough(res: Response): boolean {
  return res.headers.get('x-middleware-next') === '1'
}

describe('Authentication Middleware', () => {
  beforeEach(() => {
    process.env = { ...originalEnv }
  })

  afterAll(() => {
    process.env = originalEnv
  })

  describe('when auth is disabled', () => {
    beforeEach(() => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'false'
    })

    it('should allow access to any protected route', async () => {
      const res = await middleware(createRequest('/dashboard'))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should default to auth enabled when PEARL_WEBAPP_AUTH_ENABLED is not set', async () => {
      delete process.env.PEARL_WEBAPP_AUTH_ENABLED
      const res = await middleware(createRequest('/dashboard'))
      // Auth defaults to enabled for security -- should redirect to login
      expect(isPassThrough(res)).toBe(false)
    })
  })

  describe('bypassed paths (auth enabled)', () => {
    beforeEach(() => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'true'
      process.env.PEARL_WEBAPP_PASSCODE = 'secret'
    })

    it('should allow access to /login without auth', async () => {
      const res = await middleware(createRequest('/login'))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow access to /logout without auth', async () => {
      const res = await middleware(createRequest('/logout'))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow /_next/* paths (Next.js internals)', async () => {
      const res = await middleware(createRequest('/_next/static/chunks/main.js'))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow /favicon.ico', async () => {
      const res = await middleware(createRequest('/favicon.ico'))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow file-like paths (.png, .css, etc.)', async () => {
      const res = await middleware(createRequest('/images/logo.png'))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow manifest.json', async () => {
      const res = await middleware(createRequest('/manifest.json'))
      expect(isPassThrough(res)).toBe(true)
    })
  })

  describe('unauthenticated access to protected routes', () => {
    const TEST_PASSCODE = 'my-secret-passcode'

    beforeEach(() => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'true'
      process.env.PEARL_WEBAPP_PASSCODE = TEST_PASSCODE
    })

    it('should redirect to /login when no auth cookie is present', async () => {
      const res = await middleware(createRequest('/dashboard'))
      expect(res.status).toBe(307)
      const location = res.headers.get('location') || ''
      expect(location).toContain('/login')
      expect(location).toContain('next=%2Fdashboard')
    })

    it('should redirect when cookie value is invalid', async () => {
      const res = await middleware(createRequest('/dashboard', 'invalid-hash'))
      expect(res.status).toBe(307)
      expect(res.headers.get('location')).toContain('/login')
    })

    it('should redirect when cookie is empty', async () => {
      const res = await middleware(createRequest('/dashboard', ''))
      expect(res.status).toBe(307)
      expect(res.headers.get('location')).toContain('/login')
    })

    it('should preserve the original path in the redirect query param', async () => {
      const res = await middleware(createRequest('/some/deep/path'))
      const location = res.headers.get('location') || ''
      expect(location).toContain('next=%2Fsome%2Fdeep%2Fpath')
    })

    it('should require auth for API routes (no dot in path)', async () => {
      const res = await middleware(createRequest('/api/state'))
      expect(res.status).toBe(307)
      expect(res.headers.get('location')).toContain('/login')
    })
  })

  describe('authenticated access to protected routes', () => {
    const TEST_PASSCODE = 'my-secret-passcode'

    beforeEach(() => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'true'
      process.env.PEARL_WEBAPP_PASSCODE = TEST_PASSCODE
    })

    it('should allow access with a valid auth cookie', async () => {
      const validToken = sha256Hex(TEST_PASSCODE)
      const res = await middleware(createRequest('/dashboard', validToken))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow access to nested protected routes with valid cookie', async () => {
      const validToken = sha256Hex(TEST_PASSCODE)
      const res = await middleware(createRequest('/settings/profile', validToken))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should allow access to API routes with valid cookie', async () => {
      const validToken = sha256Hex(TEST_PASSCODE)
      const res = await middleware(createRequest('/api/state', validToken))
      expect(isPassThrough(res)).toBe(true)
    })
  })

  describe('session cookie validation', () => {
    const TEST_PASSCODE = 'session-test-passcode'

    beforeEach(() => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'true'
      process.env.PEARL_WEBAPP_PASSCODE = TEST_PASSCODE
    })

    it('should accept cookie matching SHA-256 hash of passcode', async () => {
      const validHash = sha256Hex(TEST_PASSCODE)
      const res = await middleware(createRequest('/dashboard', validHash))
      expect(isPassThrough(res)).toBe(true)
    })

    it('should reject cookie with wrong hash', async () => {
      const wrongHash = sha256Hex('wrong-passcode')
      const res = await middleware(createRequest('/dashboard', wrongHash))
      expect(res.status).toBe(307)
    })

    it('should reject cookie with raw passcode (not hashed)', async () => {
      const res = await middleware(createRequest('/dashboard', TEST_PASSCODE))
      expect(res.status).toBe(307)
    })
  })

  describe('when passcode is not configured', () => {
    beforeEach(() => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'true'
    })

    it('should return 503 when PEARL_WEBAPP_PASSCODE is empty', async () => {
      process.env.PEARL_WEBAPP_PASSCODE = ''
      const res = await middleware(createRequest('/dashboard'))
      expect(res.status).toBe(503)
    })

    it('should return 503 when PEARL_WEBAPP_PASSCODE is not set', async () => {
      delete process.env.PEARL_WEBAPP_PASSCODE
      const res = await middleware(createRequest('/dashboard'))
      expect(res.status).toBe(503)
    })
  })

  describe('config', () => {
    it('should export a matcher that excludes _next paths', () => {
      expect(config.matcher).toEqual(['/((?!_next).*)'])
    })
  })
})
