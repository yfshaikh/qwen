import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NodeDetail } from '../src/components/NodeDetail'
import type { GraphNode } from '../src/types'

const NODE: GraphNode = {
  id: 'a', label: 'Limits', type: 'concept', summary: 'approaching a value',
  mastery: 0.3, confidence: 0.8, salience: null,
  evidence: [{ kind: 'quiz_correct', content: 'ok', importance: 0.9 }],
}

describe('NodeDetail', () => {
  it('renders label, metrics, and evidence', () => {
    render(<NodeDetail node={NODE} onClose={vi.fn()} />)
    expect(screen.getByText('Limits')).toBeInTheDocument()
    expect(screen.getByText('0.30')).toBeInTheDocument()
    expect(screen.getByText(/quiz_correct/)).toBeInTheDocument()
  })

  it('renders nothing when no node is selected', () => {
    const { container } = render(<NodeDetail node={null} onClose={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })
})
