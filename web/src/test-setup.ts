import '@testing-library/jest-dom/vitest'

// React Flow uses ResizeObserver, absent in jsdom.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
  globalThis.ResizeObserver || ResizeObserverStub
