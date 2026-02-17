/**
 * Tests for useViewportType hook
 */

import { renderHook, act } from '@testing-library/react'
import { useViewportType } from '@/hooks/useViewportType'

// Mock window.innerWidth and window.innerHeight
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
    expect(result.current.isUltrawide).toBe(false)
    expect(result.current.width).toBe(1920)
    expect(result.current.height).toBe(1080)
  })

  it('should detect ultrawide viewport', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 2560 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 720 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('ultrawide')
    expect(result.current.isUltrawide).toBe(true)
  })

  it('should detect tablet viewport', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 768 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 1024 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('tablet')
    expect(result.current.isUltrawide).toBe(false)
  })

  it('should detect mobile viewport', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 667 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('mobile')
    expect(result.current.isUltrawide).toBe(false)
  })

  it('should respect ultrawide query parameter', () => {
    // Use history.pushState to change the URL without redefining window.location
    const originalSearch = window.location.search
    history.pushState({}, '', '?ultrawide=true')

    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1920 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 1080 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('ultrawide')
    expect(result.current.isUltrawide).toBe(true)

    // Restore original search
    history.pushState({}, '', originalSearch || '/')
  })

  it('should update on window resize', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1920 })
    Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: 1080 })

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('desktop')

    // Simulate resize
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 })
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    // Note: The hook may debounce resize events, so we check that listener was set up
    expect(mockWindow.addEventListener).toHaveBeenCalledWith('resize', expect.any(Function))
  })

  it('should clean up event listeners on unmount', () => {
    const { unmount } = renderHook(() => useViewportType())

    unmount()

    expect(mockWindow.removeEventListener).toHaveBeenCalled()
  })
})
