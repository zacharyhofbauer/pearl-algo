'use client'

interface SparklineProps {
  /** Y values (time-ordered). If 0–1 values, renders a flat line. */
  data: number[]
  width?: number
  height?: number
  /** If true, line is green when last > first, red otherwise. Otherwise use stroke. */
  colorByTrend?: boolean
  className?: string
}

/**
 * Lightweight SVG sparkline using polyline.
 * Renders a small 120x32px chart by default.
 */
export default function Sparkline({
  data,
  width = 120,
  height = 32,
  colorByTrend = true,
  className = '',
}: SparklineProps) {
  if (!Array.isArray(data) || data.length < 2) {
    return (
      <svg width={width} height={height} className={className} aria-hidden>
        <rect width={width} height={height} fill="transparent" />
      </svg>
    )
  }

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const pad = range * 0.1 || 1
  const yMin = min - pad
  const yMax = max + pad
  const yRange = yMax - yMin
  const n = data.length

  const points = data
    .map((v, i) => {
      const x = (i / (n - 1)) * (width - 2) + 1
      const y = height - 1 - ((v - yMin) / yRange) * (height - 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const stroke =
    colorByTrend
      ? data[data.length - 1] >= data[0]
        ? 'var(--accent-green)'
        : 'var(--accent-red)'
      : 'var(--text-tertiary)'

  return (
    <svg
      width={width}
      height={height}
      className={className}
      aria-hidden
      role="img"
      aria-label="Mini sparkline chart"
    >
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
