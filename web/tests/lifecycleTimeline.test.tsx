import { render, screen } from '@testing-library/react'
import { LifecycleTimeline } from '../src/components/evals/LifecycleTimeline'

it('renders one row per session with report counts', () => {
  render(<LifecycleTimeline snapshots={[
    { session: 0, sim_ts: 't0', graph: { nodes: [], edges: [] }, report: { nodes_created: 3, merged: 1, forgotten: 0, processed_events: 4 } },
    { session: 1, sim_ts: 't1', graph: { nodes: [], edges: [] }, report: { nodes_created: 0, merged: 0, forgotten: 2, processed_events: 2 } },
  ]} />)
  expect(screen.getByText(/session 0/i)).toBeInTheDocument()
  expect(screen.getByText(/3 created/i)).toBeInTheDocument()
  expect(screen.getByText(/2 forgotten/i)).toBeInTheDocument()
})
