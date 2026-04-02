import { formatSettingsValue, getNestedValue } from '@/lib/settings'

describe('settings helpers', () => {
  it('reads nested values safely', () => {
    const value = getNestedValue(
      {
        risk: {
          limits: {
            maxLoss: 500,
          },
        },
      },
      'risk.limits.maxLoss'
    )

    expect(value).toBe(500)
  })

  it('returns undefined for missing nested values', () => {
    expect(getNestedValue({ risk: {} }, 'risk.limits.maxLoss')).toBeUndefined()
  })

  it('formats booleans and nullish values explicitly', () => {
    expect(formatSettingsValue(true)).toBe('true')
    expect(formatSettingsValue(false)).toBe('false')
    expect(formatSettingsValue(null)).toBe('null')
    expect(formatSettingsValue(undefined)).toBe('null')
  })
})
