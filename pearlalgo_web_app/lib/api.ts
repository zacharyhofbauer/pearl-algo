/**
 * API Client with Authentication Support
 *
 * Handles API key authentication for the Pearl Algo Web App.
 * Authentication is optional and controlled by:
 * - NEXT_PUBLIC_API_KEY: API key to include in requests
 *
 * When NEXT_PUBLIC_API_KEY is set, all requests will include the X-API-Key header.
 * When not set, requests are made without authentication (for local development).
 */

import { useOperatorStore } from '@/stores'

// Get API key from environment (client-side accessible)
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || ''

function shouldAttachOperatorHeader(path: string): boolean {
  if (!path) return false
  // Interactive/operator-only endpoints
  if (path.startsWith('/api/pearl/')) return true
  if (path === '/api/kill-switch') return true
  if (path === '/api/close-all-trades') return true
  if (path === '/api/close-trade') return true
  if (path === '/api/pearl-suggestion/accept') return true
  if (path === '/api/pearl-suggestion/dismiss') return true
  if (path.startsWith('/api/operator/')) return true
  return false
}

/**
 * Determine the API base URL based on environment and context.
 *
 * Priority:
 * 1. NEXT_PUBLIC_API_URL environment variable
 * 2. ?api_port=XXXX URL parameter (for testing)
 * 3. Relative URLs on public domains, localhost:8000 for local dev
 */
export function getApiUrl(): string {
  // Check for environment variable override first
  const envUrl = process.env.NEXT_PUBLIC_API_URL
  if (envUrl) return envUrl

  if (typeof window === 'undefined') return 'http://localhost:8000' // SSR fallback
  const hostname = window.location.hostname

  // Check URL params for account switching
  const urlParams = new URLSearchParams(window.location.search)
  const account = urlParams.get('account')
  const apiPort = urlParams.get('api_port')
  const isLocal = ['localhost', '127.0.0.1'].includes(hostname)

  // Account-based switching: ?account=tv_paper uses /tv_paper/ prefix on production
  if (account === 'tv_paper') {
    if (isLocal) {
      return 'http://localhost:8001'
    }
    // On production: use /tv_paper path prefix (routed by Cloudflare tunnel)
    return '/tv_paper'
  }

  // Legacy port-based switching: ?api_port=8001 (for local dev)
  if (apiPort) {
    if (isLocal) {
      return `http://localhost:${apiPort}`
    }
    const protocol = window.location.protocol
    return `${protocol}//${hostname}:${apiPort}`
  }

  // Default: relative URLs on public domain (pearlalgo.io), localhost:8000 for local dev
  return isLocal ? 'http://localhost:8000' : ''
}

/**
 * Get headers with authentication if API key is configured.
 */
export function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }

  if (API_KEY) {
    headers['X-API-Key'] = API_KEY
  }

  return headers
}

/**
 * Fetch wrapper that automatically includes authentication headers.
 *
 * @param path - API path (e.g., '/api/state')
 * @param options - Optional fetch options to merge
 * @returns Promise<Response>
 */
export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const apiUrl = getApiUrl()
  const url = `${apiUrl}${path}`

  const headers = {
    ...getAuthHeaders(),
    ...(options.headers || {}),
  }

  // Operator unlock header (in-memory only; never persisted). Only attach to operator endpoints.
  if (shouldAttachOperatorHeader(path) && !('X-PEARL-OPERATOR' in (headers as any))) {
    try {
      const op = useOperatorStore.getState()
      op.tick()
      if (op.isUnlocked && op.passphrase) {
        ;(headers as any)['X-PEARL-OPERATOR'] = op.passphrase
      }
    } catch {
      // ignore (SSR / store init)
    }
  }

  return fetch(url, {
    ...options,
    headers,
  })
}

/**
 * Normalized API error shape for consistent error handling
 */
export interface ApiError {
  message: string
  status: number
  detail?: unknown
}

/**
 * Normalize an error response into a consistent shape
 */
export function normalizeApiError(response: Response, raw?: string): ApiError {
  let detail: unknown = null
  let message = `API Error: ${response.status}`

  if (raw) {
    try {
      const body = JSON.parse(raw)
      // Try multiple common error message fields
      const errorMessage =
        (typeof body?.detail === 'string' ? body.detail : null) ||
        (typeof body?.detail?.message === 'string' ? body.detail?.message : null) ||
        (typeof body?.message === 'string' ? body.message : null) ||
        (typeof body?.error === 'string' ? body.error : null)
      
      if (errorMessage) {
        message = errorMessage
      }
      detail = body?.detail || body
    } catch {
      // If JSON parsing fails, use raw text as message
      if (raw) {
        message = raw
        detail = raw
      }
    }
  }

  // Handle specific status codes with user-friendly messages
  if (response.status === 401) {
    message = message || 'Authentication required.'
  } else if (response.status === 403) {
    if (typeof detail === 'object' && detail !== null && 'message' in detail) {
      const detailMsg = String((detail as any).message)
      if (detailMsg.toLowerCase().includes('operator')) {
        message = 'Operator access required.'
      } else {
        message = message || 'Forbidden.'
      }
    } else {
      message = message || 'Forbidden.'
    }
  } else if (response.status === 503) {
    message = message || 'Service unavailable.'
  }

  return {
    message,
    status: response.status,
    detail,
  }
}

/**
 * Fetch JSON from API with authentication.
 *
 * @param path - API path (e.g., '/api/state')
 * @param options - Optional fetch options
 * @returns Promise<T> - Parsed JSON response
 * @throws ApiError - Normalized error with message, status, and detail
 */
export async function apiFetchJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, options)

  if (!response.ok) {
    let raw = ''
    try {
      raw = await response.text()
    } catch {
      raw = ''
    }
    
    const error = normalizeApiError(response, raw)
    
    // Throw Error with message for backward compatibility, but include status/details
    const err = new Error(error.message) as Error & ApiError
    err.status = error.status
    err.detail = error.detail
    throw err
  }

  return response.json()
}

/**
 * Check if authentication is configured.
 */
export function isAuthConfigured(): boolean {
  return Boolean(API_KEY)
}
