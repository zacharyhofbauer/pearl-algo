/**
 * @jest-environment node
 */
import crypto from 'crypto'

// -- Mocks --
// Variables prefixed with 'mock' are allowed inside jest.mock factories.

const mockCookieSet = jest.fn()
const mockRedirect = jest.fn<never, [string]>((url: string) => {
  // Next.js redirect() throws to halt execution
  throw new Error('NEXT_REDIRECT')
})

jest.mock('next/headers', () => ({
  cookies: () => ({
    set: (...args: any[]) => mockCookieSet(...args),
  }),
}))

jest.mock('next/navigation', () => ({
  redirect: (url: string) => mockRedirect(url),
}))

// Import AFTER mocks are declared
import { login } from '@/app/login/actions'
import { GET as logoutHandler } from '@/app/logout/route'

// -- Helpers --

const originalEnv = process.env

function sha256Hex(input: string): string {
  return crypto.createHash('sha256').update(input, 'utf8').digest('hex')
}

function createFormData(fields: Record<string, string>): FormData {
  const fd = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    fd.set(key, value)
  }
  return fd
}

// -- Login action tests --

describe('login server action', () => {
  const TEST_PASSCODE = 'correct-passcode-123'

  beforeEach(() => {
    mockCookieSet.mockClear()
    mockRedirect.mockClear()
    mockRedirect.mockImplementation((url: string) => {
      throw new Error('NEXT_REDIRECT')
    })
    process.env = { ...originalEnv }
    process.env.PEARL_WEBAPP_AUTH_ENABLED = 'true'
    process.env.PEARL_WEBAPP_PASSCODE = TEST_PASSCODE
  })

  afterAll(() => {
    process.env = originalEnv
  })

  describe('successful login', () => {
    it('should set session cookie and redirect on valid passcode', async () => {
      const fd = createFormData({ passcode: TEST_PASSCODE, next: '/dashboard' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).toHaveBeenCalledWith(
        'pearl_webapp_auth',
        sha256Hex(TEST_PASSCODE),
        expect.objectContaining({
          httpOnly: true,
          sameSite: 'lax',
          path: '/',
        })
      )
      expect(mockRedirect).toHaveBeenCalledWith('/dashboard')
    })

    it('should redirect to / when next is not specified', async () => {
      const fd = createFormData({ passcode: TEST_PASSCODE })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/')
    })

    it('should set secure cookie in production', async () => {
      const prevNodeEnv = process.env.NODE_ENV
      process.env.NODE_ENV = 'production'

      const fd = createFormData({ passcode: TEST_PASSCODE })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).toHaveBeenCalledWith(
        'pearl_webapp_auth',
        expect.any(String),
        expect.objectContaining({ secure: true })
      )

      process.env.NODE_ENV = prevNodeEnv
    })
  })

  describe('invalid credentials', () => {
    it('should redirect with error=invalid on wrong passcode', async () => {
      const fd = createFormData({ passcode: 'wrong-passcode', next: '/dashboard' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).not.toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith(
        '/login?error=invalid&next=%2Fdashboard'
      )
    })

    it('should trim whitespace from passcode before comparison', async () => {
      const fd = createFormData({ passcode: `  ${TEST_PASSCODE}  `, next: '/' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/')
    })
  })

  describe('empty credentials', () => {
    it('should redirect with error on empty passcode', async () => {
      const fd = createFormData({ passcode: '', next: '/' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).not.toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/login?error=invalid&next=%2F')
    })

    it('should redirect with error when passcode field is missing', async () => {
      const fd = createFormData({ next: '/' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).not.toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/login?error=invalid&next=%2F')
    })
  })

  describe('auth disabled', () => {
    it('should redirect without cookie when auth is disabled', async () => {
      process.env.PEARL_WEBAPP_AUTH_ENABLED = 'false'
      const fd = createFormData({ passcode: '', next: '/dashboard' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).not.toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/dashboard')
    })
  })

  describe('misconfigured passcode', () => {
    it('should redirect with error=misconfigured when passcode env is empty', async () => {
      process.env.PEARL_WEBAPP_PASSCODE = ''
      const fd = createFormData({ passcode: 'anything' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).not.toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/login?error=misconfigured')
    })

    it('should redirect with error=misconfigured when passcode env is not set', async () => {
      delete process.env.PEARL_WEBAPP_PASSCODE
      const fd = createFormData({ passcode: 'anything' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockCookieSet).not.toHaveBeenCalled()
      expect(mockRedirect).toHaveBeenCalledWith('/login?error=misconfigured')
    })
  })

  describe('next URL handling', () => {
    it('should use the provided next URL for redirect', async () => {
      const fd = createFormData({ passcode: TEST_PASSCODE, next: '/settings/profile' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockRedirect).toHaveBeenCalledWith('/settings/profile')
    })

    it('should sanitize next URL to prevent open redirect', async () => {
      const fd = createFormData({
        passcode: TEST_PASSCODE,
        next: 'https://evil.com/steal',
      })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockRedirect).toHaveBeenCalledWith('/')
    })

    it('should default to / when next is not provided', async () => {
      const fd = createFormData({ passcode: TEST_PASSCODE })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockRedirect).toHaveBeenCalledWith('/')
    })

    it('should preserve next URL in error redirect for invalid passcode', async () => {
      const fd = createFormData({ passcode: 'wrong', next: '/target' })

      await expect(login(fd)).rejects.toThrow('NEXT_REDIRECT')

      expect(mockRedirect).toHaveBeenCalledWith(
        '/login?error=invalid&next=%2Ftarget'
      )
    })
  })
})

// -- Logout route handler tests --

describe('logout route handler', () => {
  it('should redirect to /login', async () => {
    const request = new Request('http://localhost:3001/logout')
    const res = await logoutHandler(request)

    expect(res.status).toBe(307)
    const location = res.headers.get('location') || ''
    expect(location).toContain('/login')
  })

  it('should clear the auth cookie', async () => {
    const request = new Request('http://localhost:3001/logout')
    const res = await logoutHandler(request)

    const setCookie = res.headers.get('set-cookie') || ''
    expect(setCookie).toContain('pearl_webapp_auth=')
    expect(setCookie).toContain('Path=/')
    expect(setCookie).toContain('Expires=')
  })

  it('should construct redirect URL relative to request origin', async () => {
    const request = new Request('https://pearl.example.com/logout')
    const res = await logoutHandler(request)

    const location = res.headers.get('location') || ''
    expect(location).toBe('https://pearl.example.com/login')
  })
})
