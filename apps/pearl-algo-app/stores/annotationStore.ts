import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface ChartAnnotation {
  id: string
  time: number
  price: number
  text: string
  color: string
  createdAt: string
}

interface AnnotationState {
  annotations: ChartAnnotation[]
  addAnnotation: (annotation: Omit<ChartAnnotation, 'id' | 'createdAt'>) => void
  removeAnnotation: (id: string) => void
  updateAnnotation: (id: string, updates: Partial<ChartAnnotation>) => void
  clearAnnotations: () => void
}

export const useAnnotationStore = create<AnnotationState>()(
  persist(
    (set) => ({
      annotations: [],

      addAnnotation: (annotation) => set((state) => ({
        annotations: [
          ...state.annotations,
          {
            ...annotation,
            id: `ann-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            createdAt: new Date().toISOString(),
          }
        ]
      })),

      removeAnnotation: (id) => set((state) => ({
        annotations: state.annotations.filter(a => a.id !== id)
      })),

      updateAnnotation: (id, updates) => set((state) => ({
        annotations: state.annotations.map(a =>
          a.id === id ? { ...a, ...updates } : a
        )
      })),

      clearAnnotations: () => set({ annotations: [] }),
    }),
    {
      name: 'pearl-chart-annotations',
    }
  )
)
