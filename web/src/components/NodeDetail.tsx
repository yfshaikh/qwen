import type { GraphNode } from '../types'

function fmt(v: number | null): string {
  return v == null ? '—' : v.toFixed(2)
}

export function NodeDetail({ node, onClose }: { node: GraphNode | null; onClose: () => void }) {
  if (!node) return null
  return (
    <aside className="detail">
      <button className="detail-close" onClick={onClose} aria-label="close">
        ×
      </button>
      <h3>{node.label}</h3>
      <div className="detail-type">{node.type}</div>
      {node.summary && <p>{node.summary}</p>}
      <dl className="detail-metrics">
        <dt>mastery</dt>
        <dd>{fmt(node.mastery)}</dd>
        <dt>confidence</dt>
        <dd>{fmt(node.confidence)}</dd>
        <dt>salience</dt>
        <dd>{fmt(node.salience)}</dd>
      </dl>
      <h4>Evidence</h4>
      {node.evidence.length === 0 ? (
        <p className="muted">none yet</p>
      ) : (
        <ul>
          {node.evidence.map((e, i) => (
            <li key={i}>
              <b>{e.kind}</b>
              {e.content ? `: ${e.content}` : ''}
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
