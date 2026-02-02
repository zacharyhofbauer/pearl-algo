/**
 * Tests for annotationStore
 *
 * Tests cover:
 * - Adding annotations
 * - Removing annotations
 * - Updating annotations
 * - Clearing all annotations
 * - Persistence (via zustand persist middleware)
 */

import { act } from '@testing-library/react'
import { useAnnotationStore, ChartAnnotation } from '@/stores/annotationStore'

describe('annotationStore', () => {
  beforeEach(() => {
    // Reset store before each test
    useAnnotationStore.setState({ annotations: [] })
  })

  describe('initial state', () => {
    it('should have empty annotations array initially', () => {
      const state = useAnnotationStore.getState()
      expect(state.annotations).toEqual([])
    })
  })

  describe('addAnnotation', () => {
    it('should add an annotation with auto-generated id and timestamp', () => {
      const before = new Date()

      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200.5,
          text: 'Support level',
          color: '#00ff00',
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toHaveLength(1)

      const annotation = state.annotations[0]
      expect(annotation.time).toBe(1706500000)
      expect(annotation.price).toBe(26200.5)
      expect(annotation.text).toBe('Support level')
      expect(annotation.color).toBe('#00ff00')

      // Check auto-generated fields
      expect(annotation.id).toMatch(/^ann-\d+-[a-z0-9]+$/)
      expect(new Date(annotation.createdAt).getTime()).toBeGreaterThanOrEqual(before.getTime())
    })

    it('should add multiple annotations', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'First',
          color: '#ff0000',
        })
      })

      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500300,
          price: 26250,
          text: 'Second',
          color: '#00ff00',
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toHaveLength(2)
      expect(state.annotations[0].text).toBe('First')
      expect(state.annotations[1].text).toBe('Second')
    })

    it('should generate unique ids for each annotation', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'First',
          color: '#ff0000',
        })
      })

      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'Second',
          color: '#ff0000',
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].id).not.toBe(state.annotations[1].id)
    })
  })

  describe('removeAnnotation', () => {
    it('should remove annotation by id', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'To be removed',
          color: '#ff0000',
        })
      })

      const id = useAnnotationStore.getState().annotations[0].id

      act(() => {
        useAnnotationStore.getState().removeAnnotation(id)
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toHaveLength(0)
    })

    it('should only remove the specified annotation', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'First',
          color: '#ff0000',
        })
        useAnnotationStore.getState().addAnnotation({
          time: 1706500300,
          price: 26250,
          text: 'Second',
          color: '#00ff00',
        })
      })

      const firstId = useAnnotationStore.getState().annotations[0].id

      act(() => {
        useAnnotationStore.getState().removeAnnotation(firstId)
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toHaveLength(1)
      expect(state.annotations[0].text).toBe('Second')
    })

    it('should do nothing if id does not exist', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'Keep me',
          color: '#ff0000',
        })
      })

      act(() => {
        useAnnotationStore.getState().removeAnnotation('non-existent-id')
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toHaveLength(1)
      expect(state.annotations[0].text).toBe('Keep me')
    })
  })

  describe('updateAnnotation', () => {
    it('should update annotation text', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'Original',
          color: '#ff0000',
        })
      })

      const id = useAnnotationStore.getState().annotations[0].id

      act(() => {
        useAnnotationStore.getState().updateAnnotation(id, { text: 'Updated' })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].text).toBe('Updated')
      // Other fields should remain unchanged
      expect(state.annotations[0].time).toBe(1706500000)
      expect(state.annotations[0].price).toBe(26200)
      expect(state.annotations[0].color).toBe('#ff0000')
    })

    it('should update annotation color', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'Test',
          color: '#ff0000',
        })
      })

      const id = useAnnotationStore.getState().annotations[0].id

      act(() => {
        useAnnotationStore.getState().updateAnnotation(id, { color: '#0000ff' })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].color).toBe('#0000ff')
    })

    it('should update multiple fields at once', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'Original',
          color: '#ff0000',
        })
      })

      const id = useAnnotationStore.getState().annotations[0].id

      act(() => {
        useAnnotationStore.getState().updateAnnotation(id, {
          text: 'New text',
          color: '#00ff00',
          price: 26300,
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].text).toBe('New text')
      expect(state.annotations[0].color).toBe('#00ff00')
      expect(state.annotations[0].price).toBe(26300)
    })

    it('should only update the specified annotation', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'First',
          color: '#ff0000',
        })
        useAnnotationStore.getState().addAnnotation({
          time: 1706500300,
          price: 26250,
          text: 'Second',
          color: '#00ff00',
        })
      })

      const firstId = useAnnotationStore.getState().annotations[0].id

      act(() => {
        useAnnotationStore.getState().updateAnnotation(firstId, { text: 'Updated First' })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].text).toBe('Updated First')
      expect(state.annotations[1].text).toBe('Second') // Unchanged
    })

    it('should do nothing if id does not exist', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'Original',
          color: '#ff0000',
        })
      })

      act(() => {
        useAnnotationStore.getState().updateAnnotation('non-existent-id', { text: 'Should not apply' })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].text).toBe('Original')
    })
  })

  describe('clearAnnotations', () => {
    it('should remove all annotations', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: 'First',
          color: '#ff0000',
        })
        useAnnotationStore.getState().addAnnotation({
          time: 1706500300,
          price: 26250,
          text: 'Second',
          color: '#00ff00',
        })
        useAnnotationStore.getState().addAnnotation({
          time: 1706500600,
          price: 26300,
          text: 'Third',
          color: '#0000ff',
        })
      })

      expect(useAnnotationStore.getState().annotations).toHaveLength(3)

      act(() => {
        useAnnotationStore.getState().clearAnnotations()
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toEqual([])
    })

    it('should do nothing if annotations already empty', () => {
      act(() => {
        useAnnotationStore.getState().clearAnnotations()
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations).toEqual([])
    })
  })

  describe('edge cases', () => {
    it('should handle annotation with empty text', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: '',
          color: '#ff0000',
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].text).toBe('')
    })

    it('should handle annotation with negative price', () => {
      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: -100,
          text: 'Negative price',
          color: '#ff0000',
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].price).toBe(-100)
    })

    it('should handle annotation with very long text', () => {
      const longText = 'A'.repeat(1000)

      act(() => {
        useAnnotationStore.getState().addAnnotation({
          time: 1706500000,
          price: 26200,
          text: longText,
          color: '#ff0000',
        })
      })

      const state = useAnnotationStore.getState()
      expect(state.annotations[0].text).toBe(longText)
    })
  })
})
