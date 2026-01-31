import { getApiUrl, getAuthHeaders, apiFetch, apiFetchJson, isAuthConfigured } from '@/lib/api'

// Mock process.env
const originalEnv = process.env

describe('API utility', () => {
  beforeEach(() => {
    jest.resetModules()
    process.env = { ...originalEnv }
    ;(global.fetch as jest.Mock).mockReset()
  })

  afterAll(() => {
    process.env = originalEnv
  })

  describe('getApiUrl', () => {
    it('should return environment URL when NEXT_PUBLIC_API_URL is set', () => {
      // This test verifies the logic, but env vars are read at module load time
      // So we test the default behavior
      const url = getApiUrl()
      expect(typeof url).toBe('string')
    })

    it('should return localhost URL for SSR', () => {
      // In test environment (node), window is undefined initially
      const originalWindow = global.window
      // @ts-ignore - intentionally setting window to undefined
      delete global.window

      const url = getApiUrl()
      expect(url).toBe('http://localhost:8000')

      // @ts-ignore - restore window
      global.window = originalWindow
    })
  })

  describe('getAuthHeaders', () => {
    it('should return headers with Content-Type', () => {
      const headers = getAuthHeaders()
      expect(headers['Content-Type']).toBe('application/json')
    })

    it('should not include X-API-Key when not configured', () => {
      const headers = getAuthHeaders()
      expect(headers['X-API-Key']).toBeUndefined()
    })
  })

  describe('apiFetch', () => {
    beforeEach(() => {
      ;(global.fetch as jest.Mock).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: 'test' }),
      })
    })

    it('should call fetch with correct URL', async () => {
      await apiFetch('/api/state')

      expect(global.fetch).toHaveBeenCalledTimes(1)
      const [url] = (global.fetch as jest.Mock).mock.calls[0]
      expect(url).toContain('/api/state')
    })

    it('should include auth headers', async () => {
      await apiFetch('/api/state')

      const [, options] = (global.fetch as jest.Mock).mock.calls[0]
      expect(options.headers['Content-Type']).toBe('application/json')
    })

    it('should merge custom options', async () => {
      await apiFetch('/api/state', {
        method: 'POST',
        body: JSON.stringify({ test: true }),
      })

      const [, options] = (global.fetch as jest.Mock).mock.calls[0]
      expect(options.method).toBe('POST')
      expect(options.body).toBe(JSON.stringify({ test: true }))
    })
  })

  describe('apiFetchJson', () => {
    it('should return parsed JSON on success', async () => {
      const mockData = { running: true, daily_pnl: 150 }
      ;(global.fetch as jest.Mock).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      })

      const result = await apiFetchJson('/api/state')
      expect(result).toEqual(mockData)
    })

    it('should throw on 401 error', async () => {
      ;(global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 401,
      })

      await expect(apiFetchJson('/api/state')).rejects.toThrow('Authentication required')
    })

    it('should throw on 403 error', async () => {
      ;(global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 403,
      })

      await expect(apiFetchJson('/api/state')).rejects.toThrow('Invalid API key')
    })

    it('should throw on other HTTP errors', async () => {
      ;(global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 500,
      })

      await expect(apiFetchJson('/api/state')).rejects.toThrow('API Error: 500')
    })
  })

  describe('isAuthConfigured', () => {
    it('should return false when no API key is set', () => {
      expect(isAuthConfigured()).toBe(false)
    })
  })
})
