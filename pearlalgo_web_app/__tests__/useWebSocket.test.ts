import { renderHook, act } from '@testing-library/react'
import { useWebSocket, getWebSocketUrl, getWebSocketApiKey } from '@/hooks/useWebSocket'

// -- Mock WebSocket class --

type EventHandler = ((ev: any) => void) | null

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSING = 2
  readonly CLOSED = 3

  url: string
  readyState = MockWebSocket.CONNECTING

  onopen: EventHandler = null
  onclose: EventHandler = null
  onmessage: EventHandler = null
  onerror: EventHandler = null

  send = jest.fn()
  close = jest.fn().mockImplementation(() => {
    this.readyState = MockWebSocket.CLOSED
  })

  constructor(url: string) {
    this.url = url
    mockInstances.push(this)
  }
}

let mockInstances: MockWebSocket[]
const originalEnv = process.env

function getLastInstance(): MockWebSocket {
  return mockInstances[mockInstances.length - 1]
}

beforeEach(() => {
  mockInstances = []
  ;(global as any).WebSocket = MockWebSocket
  jest.useFakeTimers()
  process.env = { ...originalEnv }
  delete process.env.NEXT_PUBLIC_API_KEY
})

afterEach(() => {
  jest.useRealTimers()
  jest.restoreAllMocks()
  process.env = originalEnv
})

// -- useWebSocket hook --

describe('useWebSocket hook', () => {
  const TEST_URL = 'ws://localhost:8000/ws'

  describe('connection establishment', () => {
    it('should create a WebSocket connection with the given URL', () => {
      renderHook(() => useWebSocket({ url: TEST_URL }))

      expect(mockInstances).toHaveLength(1)
      expect(mockInstances[0].url).toBe(TEST_URL)
    })

    it('should set status to connecting on mount', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))

      expect(result.current.status).toBe('connecting')
    })

    it('should set status to connected when WebSocket opens', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      expect(result.current.status).toBe('connected')
    })

    it('should call onStatusChange callback on status transitions', () => {
      const onStatusChange = jest.fn()
      renderHook(() => useWebSocket({ url: TEST_URL, onStatusChange }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      expect(onStatusChange).toHaveBeenCalledWith('connecting')
      expect(onStatusChange).toHaveBeenCalledWith('connected')
    })

    it('should send auth message on open when API key is configured', () => {
      process.env.NEXT_PUBLIC_API_KEY = 'test-api-key'
      renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      expect(ws.send).toHaveBeenCalledWith(
        JSON.stringify({ type: 'auth', api_key: 'test-api-key' })
      )
    })

    it('should not send auth message when API key is not set', () => {
      renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      expect(ws.send).not.toHaveBeenCalled()
    })

    it('should reset reconnect attempts on successful connection', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      expect(result.current.reconnectAttempts).toBe(0)
    })
  })

  describe('message parsing', () => {
    it('should parse JSON messages and update lastMessage', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      const testMessage = { type: 'state_update', data: { running: true } }
      act(() => {
        ws.onmessage?.({ data: JSON.stringify(testMessage) })
      })

      expect(result.current.lastMessage).toEqual(testMessage)
    })

    it('should call onMessage callback with parsed message', () => {
      const onMessage = jest.fn()
      renderHook(() => useWebSocket({ url: TEST_URL, onMessage }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      const testMessage = { type: 'update', data: { daily_pnl: 100 } }
      act(() => {
        ws.onmessage?.({ data: JSON.stringify(testMessage) })
      })

      expect(onMessage).toHaveBeenCalledWith(testMessage)
    })

    it('should handle invalid JSON gracefully without crashing', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation()
      const onMessage = jest.fn()
      renderHook(() => useWebSocket({ url: TEST_URL, onMessage }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      act(() => {
        ws.onmessage?.({ data: 'not valid json {{{' })
      })

      expect(onMessage).not.toHaveBeenCalled()
      expect(consoleSpy).toHaveBeenCalled()
    })
  })

  describe('error handling', () => {
    it('should set status to error on WebSocket error', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.onerror?.({})
      })

      expect(result.current.status).toBe('error')
    })

    it('should not crash when WebSocket constructor throws', () => {
      jest.spyOn(console, 'error').mockImplementation()
      ;(global as any).WebSocket = class {
        constructor() {
          throw new Error('Connection refused')
        }
      }

      // Hook should mount without throwing even if the constructor fails
      expect(() => {
        renderHook(() => useWebSocket({ url: TEST_URL }))
      }).not.toThrow()

      ;(global as any).WebSocket = MockWebSocket
    })
  })

  describe('reconnection on disconnect', () => {
    it('should attempt to reconnect after disconnect', () => {
      renderHook(() =>
        useWebSocket({ url: TEST_URL, reconnect: true, reconnectInterval: 3000 })
      )
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      // Simulate disconnect: set readyState to CLOSED then trigger onclose
      act(() => {
        ws.readyState = MockWebSocket.CLOSED
        ws.onclose?.({})
      })

      expect(mockInstances).toHaveLength(1) // no reconnect yet

      act(() => {
        jest.advanceTimersByTime(3000)
      })

      expect(mockInstances).toHaveLength(2) // reconnect attempted
    })

    it('should increment reconnectAttempts on each reconnect', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: TEST_URL, reconnect: true, reconnectInterval: 1000 })
      )
      const ws = getLastInstance()

      // Trigger close (simulating failed connection)
      act(() => {
        ws.readyState = MockWebSocket.CLOSED
        ws.onclose?.({})
      })

      act(() => {
        jest.advanceTimersByTime(1000)
      })

      expect(result.current.reconnectAttempts).toBe(1)
      expect(mockInstances).toHaveLength(2)
    })

    it('should not reconnect when reconnect option is false', () => {
      renderHook(() => useWebSocket({ url: TEST_URL, reconnect: false }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.CLOSED
        ws.onclose?.({})
      })

      act(() => {
        jest.advanceTimersByTime(10000)
      })

      expect(mockInstances).toHaveLength(1) // no reconnect
    })

    it('should set status to disconnected on close', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      expect(result.current.status).toBe('connected')

      act(() => {
        ws.readyState = MockWebSocket.CLOSED
        ws.onclose?.({})
      })

      expect(result.current.status).toBe('disconnected')
    })
  })

  describe('cleanup on unmount', () => {
    it('should close the WebSocket connection on unmount', () => {
      const { unmount } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      unmount()

      expect(ws.close).toHaveBeenCalled()
    })

    it('should clear timers on unmount', () => {
      const { unmount } = renderHook(() =>
        useWebSocket({ url: TEST_URL, pingInterval: 5000 })
      )
      const ws = getLastInstance()

      // Open connection to start ping interval
      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      ws.send.mockClear()
      unmount()

      // Advance time past ping interval -- should not trigger any sends
      jest.advanceTimersByTime(10000)
      expect(ws.send).not.toHaveBeenCalled()
    })

    it('should not update state after unmount', () => {
      const onStatusChange = jest.fn()
      const { unmount } = renderHook(() =>
        useWebSocket({ url: TEST_URL, onStatusChange })
      )
      const ws = getLastInstance()

      unmount()
      const callCountAfterUnmount = onStatusChange.mock.calls.length

      // Trigger events after unmount -- should be no-ops
      ws.onopen?.({})
      ws.onmessage?.({ data: '{"type":"test"}' })
      ws.onclose?.({})
      ws.onerror?.({})

      expect(onStatusChange.mock.calls.length).toBe(callCountAfterUnmount)
    })
  })

  describe('send / refresh / close', () => {
    it('should send string messages when connected', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      act(() => {
        result.current.send('hello')
      })

      expect(ws.send).toHaveBeenCalledWith('hello')
    })

    it('should JSON-stringify object messages', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      act(() => {
        result.current.send({ type: 'command', action: 'start' })
      })

      expect(ws.send).toHaveBeenCalledWith(
        JSON.stringify({ type: 'command', action: 'start' })
      )
    })

    it('should not send when WebSocket is not open', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      // Still in CONNECTING state
      act(() => {
        result.current.send('should not send')
      })

      expect(ws.send).not.toHaveBeenCalled()
    })

    it('should send "refresh" message via refresh()', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      act(() => {
        result.current.refresh()
      })

      expect(ws.send).toHaveBeenCalledWith('refresh')
    })

    it('should close the connection via close()', () => {
      const { result } = renderHook(() => useWebSocket({ url: TEST_URL }))
      const ws = getLastInstance()

      act(() => {
        result.current.close()
      })

      expect(ws.close).toHaveBeenCalled()
    })
  })

  describe('ping interval', () => {
    it('should send ping messages at the configured interval', () => {
      renderHook(() => useWebSocket({ url: TEST_URL, pingInterval: 5000 }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      // Clear any auth message calls
      ws.send.mockClear()

      act(() => {
        jest.advanceTimersByTime(5000)
      })

      expect(ws.send).toHaveBeenCalledWith('ping')

      act(() => {
        jest.advanceTimersByTime(5000)
      })

      expect(ws.send).toHaveBeenCalledTimes(2)
    })

    it('should not send ping when connection is closed', () => {
      renderHook(() => useWebSocket({ url: TEST_URL, pingInterval: 5000 }))
      const ws = getLastInstance()

      act(() => {
        ws.readyState = MockWebSocket.OPEN
        ws.onopen?.({})
      })

      ws.send.mockClear()

      // Mark connection as closed
      ws.readyState = MockWebSocket.CLOSED

      act(() => {
        jest.advanceTimersByTime(5000)
      })

      expect(ws.send).not.toHaveBeenCalled()
    })
  })
})

  describe('multiple disconnects (reconnect ref fix)', () => {
    it('should correctly count multiple reconnect attempts without stale closure', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: true,
          reconnectInterval: 100,
          maxReconnectAttempts: 5,
        })
      )

      const ws1 = getLastInstance()
      act(() => {
        ws1.readyState = MockWebSocket.OPEN
        ws1.onopen?.({} as any)
      })

      // First disconnect
      act(() => {
        ws1.onclose?.({} as any)
      })
      act(() => { jest.advanceTimersByTime(150) })
      expect(result.current.reconnectAttempts).toBe(1)

      // Second disconnect
      const ws2 = getLastInstance()
      act(() => {
        ws2.onclose?.({} as any)
      })
      act(() => { jest.advanceTimersByTime(150) })
      expect(result.current.reconnectAttempts).toBe(2)

      // Third disconnect
      const ws3 = getLastInstance()
      act(() => {
        ws3.onclose?.({} as any)
      })
      act(() => { jest.advanceTimersByTime(150) })
      expect(result.current.reconnectAttempts).toBe(3)
    })

    it('should stop reconnecting after maxReconnectAttempts', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: true,
          reconnectInterval: 50,
          maxReconnectAttempts: 2,
        })
      )

      // First disconnect + reconnect
      const ws1 = getLastInstance()
      act(() => { ws1.onclose?.({} as any) })
      act(() => { jest.advanceTimersByTime(100) })
      expect(result.current.reconnectAttempts).toBe(1)

      // Second disconnect + reconnect
      const ws2 = getLastInstance()
      act(() => { ws2.onclose?.({} as any) })
      act(() => { jest.advanceTimersByTime(100) })
      expect(result.current.reconnectAttempts).toBe(2)

      // Third disconnect — should NOT create another instance
      const ws3 = getLastInstance()
      const instanceCountBefore = mockInstances.length
      act(() => { ws3.onclose?.({} as any) })
      act(() => { jest.advanceTimersByTime(100) })
      // No new WebSocket should have been created
      expect(mockInstances.length).toBe(instanceCountBefore)
    })

    it('should reset reconnectAttempts on manual reconnect()', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8000/ws',
          reconnect: true,
          reconnectInterval: 50,
          maxReconnectAttempts: 10,
        })
      )

      // Disconnect and wait for a reconnect
      const ws1 = getLastInstance()
      act(() => { ws1.onclose?.({} as any) })
      act(() => { jest.advanceTimersByTime(100) })
      expect(result.current.reconnectAttempts).toBe(1)

      // Manual reconnect should reset counter
      act(() => { result.current.reconnect() })
      expect(result.current.reconnectAttempts).toBe(0)
    })
  })
})

// -- getWebSocketUrl utility --
// jsdom defaults to http://localhost, so localhost-based tests work directly.
// Use history.pushState to change search params (api_port, account).

describe('getWebSocketUrl', () => {
  afterEach(() => {
    // Reset URL search params after each test
    window.history.pushState({}, '', '/')
  })

  it('should return ws://localhost:8000/ws for local development', () => {
    // jsdom default: hostname=localhost, protocol=http:
    expect(getWebSocketUrl()).toBe('ws://localhost:8000/ws')
  })

  it('should use custom api_port from URL params on localhost', () => {
    window.history.pushState({}, '', '/?api_port=9000')

    expect(getWebSocketUrl()).toBe('ws://localhost:9000/ws')
  })

  it('should handle tv_paper account on localhost', () => {
    window.history.pushState({}, '', '/?account=tv_paper')

    expect(getWebSocketUrl()).toBe('ws://localhost:8001/ws')
  })

  it('should return SSR fallback when window is undefined', () => {
    // Temporarily hide window to simulate SSR
    const origWindow = globalThis.window
    // @ts-ignore
    delete (globalThis as any).window
    try {
      // Re-import to pick up the undefined-window branch
      jest.resetModules()
      const { getWebSocketUrl: getUrlSSR } = require('@/hooks/useWebSocket')
      expect(getUrlSSR()).toBe('ws://localhost:8000/ws')
    } finally {
      ;(globalThis as any).window = origWindow
    }
  })
})

// -- getWebSocketApiKey utility --

describe('getWebSocketApiKey', () => {
  const originalEnv = process.env

  beforeEach(() => {
    process.env = { ...originalEnv }
  })

  afterAll(() => {
    process.env = originalEnv
  })

  it('should return the API key when NEXT_PUBLIC_API_KEY is set', () => {
    process.env.NEXT_PUBLIC_API_KEY = 'my-secret-key'
    expect(getWebSocketApiKey()).toBe('my-secret-key')
  })

  it('should return empty string when NEXT_PUBLIC_API_KEY is not set', () => {
    delete process.env.NEXT_PUBLIC_API_KEY
    expect(getWebSocketApiKey()).toBe('')
  })
})
