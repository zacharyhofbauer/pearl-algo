'use client'

import { useCallback, useRef } from 'react'

interface PaneDividerProps {
  onResize: (deltaY: number) => void
  onDoubleClick: () => void
}

/**
 * Draggable pane divider between chart and bottom panel.
 * Drag up/down to resize. Double-click to reset.
 */
export default function PaneDivider({ onResize, onDoubleClick }: PaneDividerProps) {
  const isDragging = useRef(false)
  const lastY = useRef(0)

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    isDragging.current = true
    lastY.current = e.clientY
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    document.body.style.cursor = 'ns-resize'
    document.body.style.userSelect = 'none'
  }, [])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging.current) return
    const delta = e.clientY - lastY.current
    lastY.current = e.clientY
    onResize(delta)
  }, [onResize])

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    isDragging.current = false
    ;(e.target as HTMLElement).releasePointerCapture(e.pointerId)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  return (
    <div
      className="pane-divider"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onDoubleClick={onDoubleClick}
      title="Drag to resize · Double-click to reset"
    >
      <div className="pane-divider-handle" />
    </div>
  )
}
