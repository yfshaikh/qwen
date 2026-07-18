import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReviewQueueCard } from './ReviewQueueCard'

describe('ReviewQueueCard', () => {
  it('renders each item label and reason', () => {
    render(<ReviewQueueCard items={[
      { node_id: 'a', label: 'Limits', score: 0.8, reason: 'weak (10%) and prerequisite of 2 struggling concepts' },
    ]} onAsk={() => {}} />)
    expect(screen.getByText('Limits')).toBeInTheDocument()
    expect(screen.getByText(/prerequisite of 2/)).toBeInTheDocument()
  })
})
