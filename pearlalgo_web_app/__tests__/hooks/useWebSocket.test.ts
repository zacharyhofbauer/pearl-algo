/**
 * Tests for useWebSocket hook
 *
 * Tests cover:
 * - Connection lifecycle (connect, disconnect, cleanup)
 * - Reconnection logic (automatic retry, max attempts)
 * - Authentication handling
 * - Message handling
 * - Ping/pong keepalive
 */

import { renderHook, act, waitFor } from '@testing-library/react'
import { useWebSocket, getWebSocketUrl, getWebSocketApiKey } from '@/hooks/useWebSocket'

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  static OPEN = 1
  static CLOSED = 3

  url: string
  readyState: number = 0
  onopen: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  sentMessages: string[] = []
  closeCode?: number
  closeReason?: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: string) {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error('WebSocket is not open')
    }
    this.sentMessages.push(data)
  }

  close(code?: number, reason?: string) {
    this.closeCode = code
    this.closeReason = reason
    this.readyState = MockWebSocket.CLOSED
    if (this.onclose) {
      this.onclose(new CloseEvent('close', { code, reason }))
    }
  }

  // Test helpers
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN
    if (this.onopen) {
      this.onopen(new Event('open'))
    }
  }

  simulateMessage(data: object) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }))
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror(new Event('error'))
    }
  }
}

// Store original WebSocket
const originalWebSocket = global.WebSocket

describe('useWebSocket', () => {
  beforeEach(() => {
    // Clear mock instances
    MockWebSocket.instances = []
    // Replace global WebSocket
    global.WebSocket = MockWebSocket as unknown as typeof WebSocket
    // Clear timers
    jest.useFakeTimers()
  })

  afterEach(() => {
    // Restore WebSocket
    global.WebSocket = originalWebSocket
    jest.useRealTimers()
  })

  describe('connection lifecycle', () => {
    it('should connect on mount', () => {
      renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      expect(MockWebSocket.instances).toHaveLength(1)
      expect(MockWebSocket.instances[0].url).toBe('ws://localhost:8000/ws')
    })

    it('should update status to connected when WebSocket opens', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      expect(result.current.status).toBe('connecting')

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      expect(result.current.status).toBe('connected')
    })

    it('should update status to disconnected when WebSocket closes', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: false, // Disable reconnection for this test
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      expect(result.current.status).toBe('connected')

      act(() => {
        MockWebSocket.instances[0].close()
      })

      expect(result.current.status).toBe('disconnected')
    })

    it('should update status to error on WebSocket error', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateError()
      })

      expect(result.current.status).toBe('error')
    })

    it('should clean up WebSocket on unmount', () => {
      const { unmount } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      const ws = MockWebSocket.instances[0]
      act(() => {
        ws.simulateOpen()
      })

      unmount()

      // WebSocket should be closed
      expect(ws.readyState).toBe(MockWebSocket.CLOSED)
    })
  })

  describe('reconnection logic', () => {
    it('should attempt reconnection after disconnect', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: true,
          reconnectInterval: 1000,
          maxReconnectAttempts: 3,
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      expect(MockWebSocket.instances).toHaveLength(1)

      // Disconnect
      act(() => {
        MockWebSocket.instances[0].close()
      })

      // Advance timer for reconnection
      act(() => {
        jest.advanceTimersByTime(1000)
      })

      // Should have created a new WebSocket
      expect(MockWebSocket.instances).toHaveLength(2)
      expect(result.current.reconnectAttempts).toBe(1)
    })

    it('should stop reconnecting after max attempts', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: true,
          reconnectInterval: 100,
          maxReconnectAttempts: 2,
        })
      )

      // First connection opens and closes
      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })
      act(() => {
        MockWebSocket.instances[0].close()
      })

      // First reconnection attempt
      act(() => {
        jest.advanceTimersByTime(100)
      })
      expect(MockWebSocket.instances).toHaveLength(2)

      // Second reconnection attempt
      act(() => {
        MockWebSocket.instances[1].close()
      })
      act(() => {
        jest.advanceTimersByTime(100)
      })
      expect(MockWebSocket.instances).toHaveLength(3)

      // Third attempt should not happen (max = 2)
      act(() => {
        MockWebSocket.instances[2].close()
      })
      act(() => {
        jest.advanceTimersByTime(100)
      })

      // Should still be 3 (no more reconnection attempts)
      expect(MockWebSocket.instances).toHaveLength(3)
    })

    it('should reset reconnect attempts on successful connection', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: true,
          reconnectInterval: 100,
          maxReconnectAttempts: 5,
        })
      )

      // Initial connection and disconnect
      act(() => {
        MockWebSocket.instances[0].simulateOpen()
        MockWebSocket.instances[0].close()
      })

      // Wait for reconnection
      act(() => {
        jest.advanceTimersByTime(100)
      })

      expect(result.current.reconnectAttempts).toBe(1)

      // Successfully reconnect
      act(() => {
        MockWebSocket.instances[1].simulateOpen()
      })

      expect(result.current.reconnectAttempts).toBe(0)
    })

    it('should allow manual reconnection', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: false,
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
        MockWebSocket.instances[0].close()
      })

      expect(MockWebSocket.instances).toHaveLength(1)

      // Manual reconnect
      act(() => {
        result.current.reconnect()
      })

      expect(MockWebSocket.instances).toHaveLength(2)
    })
  })

  describe('message handling', () => {
    it('should call onMessage callback with parsed JSON', async () => {
      const onMessage = jest.fn()

      renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          onMessage,
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      act(() => {
        MockWebSocket.instances[0].simulateMessage({ type: 'state_update', data: { running: true } })
      })

      expect(onMessage).toHaveBeenCalledWith({ type: 'state_update', data: { running: true } })
    })

    it('should update lastMessage state', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      expect(result.current.lastMessage).toBeNull()

      act(() => {
        MockWebSocket.instances[0].simulateMessage({ type: 'test', data: 'hello' })
      })

      expect(result.current.lastMessage).toEqual({ type: 'test', data: 'hello' })
    })

    it('should send messages correctly', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      act(() => {
        result.current.send('ping')
      })

      expect(MockWebSocket.instances[0].sentMessages).toContain('ping')
    })

    it('should send JSON objects as strings', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      act(() => {
        result.current.send({ type: 'command', action: 'refresh' })
      })

      expect(MockWebSocket.instances[0].sentMessages).toContain(
        JSON.stringify({ type: 'command', action: 'refresh' })
      )
    })

    it('should send refresh command', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      act(() => {
        result.current.refresh()
      })

      expect(MockWebSocket.instances[0].sentMessages).toContain('refresh')
    })
  })

  describe('ping/pong keepalive', () => {
    it('should send ping at configured interval', async () => {
      renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          pingInterval: 5000,
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      expect(MockWebSocket.instances[0].sentMessages).not.toContain('ping')

      // Advance to first ping
      act(() => {
        jest.advanceTimersByTime(5000)
      })

      expect(MockWebSocket.instances[0].sentMessages).toContain('ping')
    })
  })

  describe('status change callback', () => {
    it('should call onStatusChange with status updates', async () => {
      const onStatusChange = jest.fn()

      renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          onStatusChange,
        })
      )

      expect(onStatusChange).toHaveBeenCalledWith('connecting')

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      expect(onStatusChange).toHaveBeenCalledWith('connected')
    })
  })

  describe('close functionality', () => {
    it('should close connection when close() is called', async () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
        })
      )

      act(() => {
        MockWebSocket.instances[0].simulateOpen()
      })

      act(() => {
        result.current.close()
      })

      expect(MockWebSocket.instances[0].readyState).toBe(MockWebSocket.CLOSED)
    })
  })
})

describe('getWebSocketUrl', () => {
  const originalWindow = global.window

  afterEach(() => {
    global.window = originalWindow
  })

  it('should return localhost URL for SSR', () => {
    // @ts-ignore - testing SSR
    delete global.window
    expect(getWebSocketUrl()).toBe('ws://localhost:8000/ws')
  })

  it('should return localhost URL for localhost hostname', () => {
    global.window = {
      location: {
        hostname: 'localhost',
        protocol: 'http:',
        search: '',
      },
    } as unknown as Window & typeof globalThis

    expect(getWebSocketUrl()).toBe('ws://localhost:8000/ws')
  })

  it('should return secure WebSocket for production', () => {
    global.window = {
      location: {
        hostname: 'pearlalgo.io',
        protocol: 'https:',
        search: '',
      },
    } as unknown as Window & typeof globalThis

    expect(getWebSocketUrl()).toBe('wss://pearlalgo.io/ws')
  })

  it('should use api_port query parameter if provided', () => {
    global.window = {
      location: {
        hostname: 'localhost',
        protocol: 'http:',
        search: '?api_port=9000',
      },
    } as unknown as Window & typeof globalThis

    expect(getWebSocketUrl()).toBe('ws://localhost:9000/ws')
  })
})

describe('getWebSocketApiKey', () => {
  const originalEnv = process.env

  beforeEach(() => {
    process.env = { ...originalEnv }
  })

  afterEach(() => {
    process.env = originalEnv
  })

  it('should return empty string when no API key configured', () => {
    delete process.env.NEXT_PUBLIC_API_KEY
    expect(getWebSocketApiKey()).toBe('')
  })

  it('should return API key when configured', () => {
    process.env.NEXT_PUBLIC_API_KEY = 'test-api-key-123'
    expect(getWebSocketApiKey()).toBe('test-api-key-123')
  })
})
