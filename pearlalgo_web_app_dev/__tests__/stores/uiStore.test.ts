import { useUIStore, selectWsStatus, selectIsConnected, selectNotifications } from '@/stores/uiStore'
import { act } from '@testing-library/react'

describe('uiStore', () => {
  beforeEach(() => {
    // Reset store before each test (but preserve persisted state pattern)
    useUIStore.setState({
      wsStatus: 'disconnected',
      isLive: false,
      lastUpdate: null,
      theme: 'dark',
      showHelp: false,
      notifications: [],
    })
  })

  describe('initial state', () => {
    it('should have disconnected WebSocket status', () => {
      const state = useUIStore.getState()
      expect(state.wsStatus).toBe('disconnected')
    })

    it('should not be live initially', () => {
      const state = useUIStore.getState()
      expect(state.isLive).toBe(false)
    })

    it('should have dark theme by default', () => {
      const state = useUIStore.getState()
      expect(state.theme).toBe('dark')
    })

    it('should have empty notifications', () => {
      const state = useUIStore.getState()
      expect(state.notifications).toEqual([])
    })
  })

  describe('setWsStatus', () => {
    it('should update WebSocket status', () => {
      act(() => {
        useUIStore.getState().setWsStatus('connected')
      })

      const state = useUIStore.getState()
      expect(state.wsStatus).toBe('connected')
    })

    it('should handle all status values', () => {
      const statuses = ['connecting', 'connected', 'disconnected', 'error'] as const

      statuses.forEach((status) => {
        act(() => {
          useUIStore.getState().setWsStatus(status)
        })

        const state = useUIStore.getState()
        expect(state.wsStatus).toBe(status)
      })
    })
  })

  describe('setIsLive', () => {
    it('should set live status to true', () => {
      act(() => {
        useUIStore.getState().setIsLive(true)
      })

      const state = useUIStore.getState()
      expect(state.isLive).toBe(true)
    })

    it('should set live status to false', () => {
      act(() => {
        useUIStore.getState().setIsLive(true)
      })

      act(() => {
        useUIStore.getState().setIsLive(false)
      })

      const state = useUIStore.getState()
      expect(state.isLive).toBe(false)
    })
  })

  describe('setLastUpdate', () => {
    it('should set last update time', () => {
      const now = new Date()

      act(() => {
        useUIStore.getState().setLastUpdate(now)
      })

      const state = useUIStore.getState()
      expect(state.lastUpdate).toEqual(now)
    })
  })

  describe('setTheme', () => {
    it('should switch to light theme', () => {
      act(() => {
        useUIStore.getState().setTheme('light')
      })

      const state = useUIStore.getState()
      expect(state.theme).toBe('light')
    })

    it('should switch back to dark theme', () => {
      act(() => {
        useUIStore.getState().setTheme('light')
      })

      act(() => {
        useUIStore.getState().setTheme('dark')
      })

      const state = useUIStore.getState()
      expect(state.theme).toBe('dark')
    })
  })

  describe('toggleHelp', () => {
    it('should toggle help panel visibility', () => {
      expect(useUIStore.getState().showHelp).toBe(false)

      act(() => {
        useUIStore.getState().toggleHelp()
      })

      expect(useUIStore.getState().showHelp).toBe(true)

      act(() => {
        useUIStore.getState().toggleHelp()
      })

      expect(useUIStore.getState().showHelp).toBe(false)
    })
  })

  describe('notifications', () => {
    describe('addNotification', () => {
      it('should add a notification with generated id and timestamp', () => {
        act(() => {
          useUIStore.getState().addNotification({
            type: 'success',
            title: 'Trade Executed',
            message: 'Long position opened',
          })
        })

        const state = useUIStore.getState()
        expect(state.notifications).toHaveLength(1)
        expect(state.notifications[0].type).toBe('success')
        expect(state.notifications[0].title).toBe('Trade Executed')
        expect(state.notifications[0].message).toBe('Long position opened')
        expect(state.notifications[0].id).toMatch(/^notif-/)
        expect(state.notifications[0].timestamp).toBeInstanceOf(Date)
      })

      it('should add multiple notifications', () => {
        act(() => {
          useUIStore.getState().addNotification({
            type: 'info',
            title: 'Info 1',
          })
        })

        act(() => {
          useUIStore.getState().addNotification({
            type: 'warning',
            title: 'Warning 1',
          })
        })

        const state = useUIStore.getState()
        expect(state.notifications).toHaveLength(2)
        expect(state.notifications[0].title).toBe('Info 1')
        expect(state.notifications[1].title).toBe('Warning 1')
      })
    })

    describe('removeNotification', () => {
      it('should remove a notification by id', () => {
        act(() => {
          useUIStore.getState().addNotification({
            type: 'error',
            title: 'Error',
          })
        })

        const id = useUIStore.getState().notifications[0].id

        act(() => {
          useUIStore.getState().removeNotification(id)
        })

        const state = useUIStore.getState()
        expect(state.notifications).toHaveLength(0)
      })

      it('should only remove the specified notification', () => {
        act(() => {
          useUIStore.getState().addNotification({ type: 'info', title: 'First' })
        })
        act(() => {
          useUIStore.getState().addNotification({ type: 'info', title: 'Second' })
        })

        const firstId = useUIStore.getState().notifications[0].id

        act(() => {
          useUIStore.getState().removeNotification(firstId)
        })

        const state = useUIStore.getState()
        expect(state.notifications).toHaveLength(1)
        expect(state.notifications[0].title).toBe('Second')
      })
    })

    describe('clearNotifications', () => {
      it('should clear all notifications', () => {
        act(() => {
          useUIStore.getState().addNotification({ type: 'info', title: 'First' })
        })
        act(() => {
          useUIStore.getState().addNotification({ type: 'info', title: 'Second' })
        })
        act(() => {
          useUIStore.getState().addNotification({ type: 'info', title: 'Third' })
        })

        act(() => {
          useUIStore.getState().clearNotifications()
        })

        const state = useUIStore.getState()
        expect(state.notifications).toHaveLength(0)
      })
    })
  })

  describe('selectors', () => {
    describe('selectWsStatus', () => {
      it('should return WebSocket status', () => {
        act(() => {
          useUIStore.getState().setWsStatus('connected')
        })

        const state = useUIStore.getState()
        expect(selectWsStatus(state)).toBe('connected')
      })
    })

    describe('selectIsConnected', () => {
      it('should return true when connected', () => {
        act(() => {
          useUIStore.getState().setWsStatus('connected')
        })

        const state = useUIStore.getState()
        expect(selectIsConnected(state)).toBe(true)
      })

      it('should return false when not connected', () => {
        act(() => {
          useUIStore.getState().setWsStatus('disconnected')
        })

        const state = useUIStore.getState()
        expect(selectIsConnected(state)).toBe(false)
      })
    })

    describe('selectNotifications', () => {
      it('should return notifications array', () => {
        act(() => {
          useUIStore.getState().addNotification({ type: 'info', title: 'Test' })
        })

        const state = useUIStore.getState()
        const notifications = selectNotifications(state)
        expect(notifications).toHaveLength(1)
        expect(notifications[0].title).toBe('Test')
      })
    })
  })
})
