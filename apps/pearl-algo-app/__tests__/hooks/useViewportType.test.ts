/**
 * Tests for useViewportType hook
 */

import { renderHook } from '@testing-library/react'
import { useViewportType } from '@/hooks/useViewportType'

const mockWindow = {
  innerWidth: 1920,
  innerHeight: 1080,
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
}

beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', {
    writable: true,
    configurable: true,
    value: mockWindow.innerWidth,
  })
  Object.defineProperty(window, 'innerHeight', {
    writable: true,
    configurable: true,
    value: mockWindow.innerHeight,
  })
  window.addEventListener = mockWindow.addEventListener
  window.removeEventListener = mockWindow.removeEventListener
})

afterEach(() => {
  jest.clearAllMocks()
})

describe('useViewportType', () => {
  it('should detect desktop viewport', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1920 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 1080 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('desktop')
    expect(result.current.width).toBe(1920)
    expect(result.current.height).toBe(1080)
  })

  it('should detect tablet viewport', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 768 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 1024 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('tablet')
  })

  it('should detect mobile viewport', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 667 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('mobile')
  })

  it('should update on window resize', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1920 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 1080 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('desktop')
    expect(mockWindow.addEventListener).toHaveBeenCalledWith('resize', expect.any(Function))
  })

  it('should clean up event listeners on unmount', () => {
    const { unmount } = renderHook(() => useViewportType())

    unmount()

    expect(mockWindow.removeEventListener).toHaveBeenCalled()
  })
})
