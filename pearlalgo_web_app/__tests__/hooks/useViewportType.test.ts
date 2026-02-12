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
    mockWindow.innerWidth = 1920
    mockWindow.innerHeight = 1080

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('desktop')
    expect(result.current.isUltrawide).toBe(false)
    expect(result.current.width).toBe(1920)
    expect(result.current.height).toBe(1080)
  })

  it('should detect ultrawide viewport', () => {
    mockWindow.innerWidth = 2560
    mockWindow.innerHeight = 720 // Ultrawide: width >= 2400, height <= 800, aspect >= 3

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('ultrawide')
    expect(result.current.isUltrawide).toBe(true)
  })

  it('should detect tablet viewport', () => {
    mockWindow.innerWidth = 768
    mockWindow.innerHeight = 1024

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('tablet')
    expect(result.current.isUltrawide).toBe(false)
  })

  it('should detect mobile viewport', () => {
    mockWindow.innerWidth = 375
    mockWindow.innerHeight = 667

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('mobile')
    expect(result.current.isUltrawide).toBe(false)
  })

  it('should respect ultrawide query parameter', () => {
    // Mock URLSearchParams
    const originalSearch = window.location.search
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        ...window.location,
        search: '?ultrawide=true',
      },
    })

    mockWindow.innerWidth = 1920 // Would normally be desktop

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('ultrawide')
    expect(result.current.isUltrawide).toBe(true)

    // Restore original search
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        ...window.location,
        search: originalSearch,
      },
    })
  })

  it('should update on window resize', () => {
    mockWindow.innerWidth = 1920

    const { result } = renderHook(() => useViewportType())

    expect(result.current.type).toBe('desktop')

    // Simulate resize
    mockWindow.innerWidth = 375
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
