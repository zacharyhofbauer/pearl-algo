'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetchJson, type ApiError } from '@/lib/api'

interface UseApiRequestOptions<T> {
  /** API path to fetch */
  path: string
  /** Optional fetch options */
  options?: RequestInit
  /** Whether to execute immediately on mount (default: false) */
  immediate?: boolean
  /** Transform function to apply to response data */
  transform?: (data: any) => T
}

interface UseApiRequestReturn<T> {
  /** Response data (null until first successful fetch) */
  data: T | null
  /** Whether a request is currently in progress */
  isLoading: boolean
  /** Error if request failed (null if successful) */
  error: ApiError | null
  /** Execute the request */
  execute: () => Promise<void>
  /** Reset state (clear data and error) */
  reset: () => void
}

/**
 * Generic hook for API requests with loading/error/success state management.
 * Provides consistent error handling and state management across components.
 */
export function useApiRequest<T = any>({
  path,
  options = {},
  immediate = false,
  transform,
}: UseApiRequestOptions<T>): UseApiRequestReturn<T> {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(immediate)
  const [error, setError] = useState<ApiError | null>(null)

  const execute = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await apiFetchJson<T>(path, options)
      const transformed = transform ? transform(response) : response
      setData(transformed)
    } catch (err) {
      // apiFetchJson throws Error with ApiError properties
      if (err instanceof Error && 'status' in err) {
        setError({
          message: err.message,
          status: (err as any).status,
          detail: (err as any).detail,
        })
      } else {
        setError({
          message: err instanceof Error ? err.message : 'Unknown error',
          status: 0,
          detail: err,
        })
      }
      setData(null)
    } finally {
      setIsLoading(false)
    }
  }, [path, options, transform])

  const reset = useCallback(() => {
    setData(null)
    setError(null)
    setIsLoading(false)
  }, [])

  // Execute immediately if requested
  useEffect(() => {
    if (immediate) {
      execute()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [immediate]) // Only run on mount if immediate is true

  return {
    data,
    isLoading,
    error,
    execute,
    reset,
  }
}

export default useApiRequest
