/** Bridges a text selection to the clicky cursor (pointer→menu morph) and the
 *  ask-action back — a module-level singleton, ported verbatim from Marfini.
 *  Neither component has to lift state across the App/board boundary. */

export interface SelectionTarget {
  /** The highlighted text, forwarded when the user asks about it. */
  text: string
  /** Viewport rect from Range.getBoundingClientRect() (can go stale on scroll). */
  rect: DOMRect
}

let current: SelectionTarget | null = null
const changeListeners = new Set<() => void>()
const askListeners = new Set<(text: string) => void>()

export function setSelection(target: SelectionTarget | null): void {
  current = target
  for (const fn of changeListeners) fn()
}

export function getSelection(): SelectionTarget | null {
  return current
}

export function onSelectionChanged(fn: () => void): () => void {
  changeListeners.add(fn)
  return () => changeListeners.delete(fn)
}

/** Fire the ask for the current selection. No-op when empty. */
export function requestAsk(): void {
  if (!current) return
  const text = current.text
  for (const fn of askListeners) fn(text)
}

export function onAskRequested(fn: (text: string) => void): () => void {
  askListeners.add(fn)
  return () => askListeners.delete(fn)
}
