'use client'

import { ReactNode, useState, useRef, useEffect } from 'react'

interface InfoTooltipProps {
  text: string
  position?: 'top' | 'bottom' | 'left' | 'right'
  children?: ReactNode
}

export function InfoTooltip({ text, position = 'top', children }: InfoTooltipProps) {
  const [isVisible, setIsVisible] = useState(false)
  const [adjustedPosition, setAdjustedPosition] = useState(position)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (isVisible && tooltipRef.current && containerRef.current) {
      const tooltip = tooltipRef.current
      const container = containerRef.current
      const tooltipRect = tooltip.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()

      // Adjust position if tooltip would go off screen
      let newPosition = position

      if (position === 'top' && tooltipRect.top < 0) {
        newPosition = 'bottom'
      } else if (position === 'bottom' && tooltipRect.bottom > window.innerHeight) {
        newPosition = 'top'
      } else if (position === 'left' && tooltipRect.left < 0) {
        newPosition = 'right'
      } else if (position === 'right' && tooltipRect.right > window.innerWidth) {
        newPosition = 'left'
      }

      // Also check horizontal overflow for top/bottom positions
      if ((position === 'top' || position === 'bottom') && tooltipRect.left < 0) {
        tooltip.style.left = '0'
        tooltip.style.transform = position === 'top'
          ? 'translateY(-100%)'
          : 'translateY(0)'
      } else if ((position === 'top' || position === 'bottom') && tooltipRect.right > window.innerWidth) {
        tooltip.style.left = 'auto'
        tooltip.style.right = '0'
        tooltip.style.transform = position === 'top'
          ? 'translateY(-100%)'
          : 'translateY(0)'
      }

      setAdjustedPosition(newPosition)
    }
  }, [isVisible, position])

  return (
    <span
      ref={containerRef}
      className="info-tooltip-container"
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
    >
      {children || (
        <span className="info-tooltip-icon">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0a8 8 0 100 16A8 8 0 008 0zm1 12H7V7h2v5zM8 6a1 1 0 110-2 1 1 0 010 2z"/>
          </svg>
        </span>
      )}
      {isVisible && (
        <div
          ref={tooltipRef}
          className={`info-tooltip info-tooltip-${adjustedPosition}`}
          role="tooltip"
        >
          {text}
          <span className="info-tooltip-arrow" />
        </div>
      )}
    </span>
  )
}

export default InfoTooltip
