import { parseWebSocketMessage, validateCandles, validateMarkers, validateAgentState } from '@/lib/schemas'

describe('parseWebSocketMessage', () => {
  it('parses valid state_update message', () => {
    const msg = parseWebSocketMessage(JSON.stringify({
      type: 'state_update',
      data: { running: true, daily_pnl: 150 },
    }))
    expect(msg).not.toBeNull()
    expect(msg?.type).toBe('state_update')
  })

  it('parses valid initial_state message', () => {
    const msg = parseWebSocketMessage(JSON.stringify({
      type: 'initial_state',
      data: { running: false },
    }))
    expect(msg).not.toBeNull()
    expect(msg?.type).toBe('initial_state')
  })

  it('parses pong message', () => {
    const msg = parseWebSocketMessage(JSON.stringify({ type: 'pong' }))
    expect(msg).not.toBeNull()
    expect(msg?.type).toBe('pong')
  })

  it('parses error message', () => {
    const msg = parseWebSocketMessage(JSON.stringify({
      type: 'error',
      message: 'something went wrong',
    }))
    expect(msg).not.toBeNull()
    expect(msg?.type).toBe('error')
  })

  it('returns null for invalid JSON', () => {
    const msg = parseWebSocketMessage('not json')
    expect(msg).toBeNull()
  })

  it('allows unknown message types (forward compat)', () => {
    const msg = parseWebSocketMessage(JSON.stringify({
      type: 'new_future_type',
      data: { foo: 'bar' },
    }))
    // Should still return something since it has a type field
    expect(msg).not.toBeNull()
  })

  it('returns null for non-object payloads', () => {
    const msg = parseWebSocketMessage(JSON.stringify('just a string'))
    expect(msg).toBeNull()
  })
})

describe('validateCandles', () => {
  it('validates valid candle array', () => {
    const candles = [
      { time: 1234567890, open: 100, high: 105, low: 95, close: 102, volume: 1000 },
      { time: 1234567900, open: 102, high: 108, low: 100, close: 106 },
    ]
    const result = validateCandles(candles)
    expect(result).not.toBeNull()
    expect(result).toHaveLength(2)
  })

  it('returns null for invalid candle data', () => {
    const result = validateCandles([{ time: 'invalid', open: 100 }])
    expect(result).toBeNull()
  })

  it('returns null for non-array', () => {
    const result = validateCandles({ time: 123, open: 100 })
    expect(result).toBeNull()
  })
})

describe('validateMarkers', () => {
  it('validates valid marker array', () => {
    const markers = [{
      time: 1234567890,
      position: 'aboveBar' as const,
      color: '#ff0000',
      shape: 'arrowDown' as const,
      text: 'EXIT',
      kind: 'exit' as const,
      pnl: -50,
    }]
    const result = validateMarkers(markers)
    expect(result).not.toBeNull()
    expect(result).toHaveLength(1)
  })

  it('returns null for invalid marker shape', () => {
    const result = validateMarkers([{
      time: 123,
      position: 'aboveBar',
      color: '#ff0000',
      shape: 'invalidShape',
      text: 'X',
    }])
    expect(result).toBeNull()
  })
})

describe('validateAgentState', () => {
  it('validates valid partial agent state', () => {
    expect(validateAgentState({ running: true, daily_pnl: 100 })).toBe(true)
  })

  it('rejects null', () => {
    expect(validateAgentState(null)).toBe(false)
  })

  it('rejects non-objects', () => {
    expect(validateAgentState('string')).toBe(false)
    expect(validateAgentState(42)).toBe(false)
  })

  it('accepts empty object (permissive)', () => {
    expect(validateAgentState({})).toBe(true)
  })

  it('accepts object with extra fields (passthrough)', () => {
    expect(validateAgentState({ running: true, new_future_field: 'hello' })).toBe(true)
  })
})
