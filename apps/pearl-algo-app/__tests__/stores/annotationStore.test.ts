/**
 * Tests for annotationStore
 */

import { act } from '@testing-library/react'
import { useAnnotationStore, type ChartAnnotation } from '@/stores/annotationStore'

beforeEach(() => {
  // Clear store before each test
  useAnnotationStore.getState().clearAnnotations()
})

describe('annotationStore', () => {
  describe('addAnnotation', () => {
    it('should add annotation with generated ID and timestamp', () => {
      const store = useAnnotationStore.getState()
      
      act(() => {
        store.addAnnotation({
          time: 1000,
          price: 100,
          text: 'Test annotation',
          color: '#ff0000',
        })
      })

      const annotations = useAnnotationStore.getState().annotations
      expect(annotations).toHaveLength(1)
      expect(annotations[0].text).toBe('Test annotation')
      expect(annotations[0].id).toBeTruthy()
      expect(annotations[0].createdAt).toBeTruthy()
    })

    it('should add multiple annotations', () => {
      const store = useAnnotationStore.getState()
      
      act(() => {
        store.addAnnotation({ time: 1000, price: 100, text: 'First', color: '#ff0000' })
        store.addAnnotation({ time: 2000, price: 200, text: 'Second', color: '#00ff00' })
      })

      const annotations = useAnnotationStore.getState().annotations
      expect(annotations).toHaveLength(2)
    })
  })

  describe('removeAnnotation', () => {
    it('should remove annotation by ID', () => {
      const store = useAnnotationStore.getState()
      let annotationId: string

      act(() => {
        store.addAnnotation({ time: 1000, price: 100, text: 'Test', color: '#ff0000' })
        annotationId = useAnnotationStore.getState().annotations[0].id
        store.removeAnnotation(annotationId)
      })

      const annotations = useAnnotationStore.getState().annotations
      expect(annotations).toHaveLength(0)
    })

    it('should not remove non-existent annotation', () => {
      const store = useAnnotationStore.getState()
      
      act(() => {
        store.addAnnotation({ time: 1000, price: 100, text: 'Test', color: '#ff0000' })
        const beforeCount = useAnnotationStore.getState().annotations.length
        store.removeAnnotation('non-existent-id')
        const afterCount = useAnnotationStore.getState().annotations.length
        expect(afterCount).toBe(beforeCount)
      })
    })
  })

  describe('updateAnnotation', () => {
    it('should update annotation fields', () => {
      const store = useAnnotationStore.getState()
      let annotationId: string

      act(() => {
        store.addAnnotation({ time: 1000, price: 100, text: 'Original', color: '#ff0000' })
        annotationId = useAnnotationStore.getState().annotations[0].id
        store.updateAnnotation(annotationId, { text: 'Updated', color: '#00ff00' })
      })

      const annotation = useAnnotationStore.getState().annotations.find(a => a.id === annotationId)
      expect(annotation?.text).toBe('Updated')
      expect(annotation?.color).toBe('#00ff00')
      expect(annotation?.time).toBe(1000) // Other fields unchanged
    })
  })

  describe('clearAnnotations', () => {
    it('should remove all annotations', () => {
      const store = useAnnotationStore.getState()
      
      act(() => {
        store.addAnnotation({ time: 1000, price: 100, text: 'First', color: '#ff0000' })
        store.addAnnotation({ time: 2000, price: 200, text: 'Second', color: '#00ff00' })
        store.clearAnnotations()
      })

      const annotations = useAnnotationStore.getState().annotations
      expect(annotations).toHaveLength(0)
    })
  })
})
