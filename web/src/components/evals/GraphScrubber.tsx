import { useEffect, useState } from 'react'
import * as api from '../../api'
import type { EvalSnapshot, GraphResponse } from '../../types'
import { GraphView } from '../GraphView'

// Map a run snapshot's graph into the shape GraphView expects. Forgotten nodes
// are KEPT (so the graph doesn't visibly shrink as memory decays) but ghosted:
// salience pinned to 0 and a suffix on the label.
function toGraphResponse(snap: EvalSnapshot): GraphResponse {
  const nodes = snap.graph.nodes.map((n) => {
    // Snapshots are captured with include_forgotten=True; a non-null
    // forgotten_at marks a decayed node the backend kept for the record.
    const forgotten = (n as { forgotten_at?: string | null }).forgotten_at != null
    const base = { ...n, summary: n.summary ?? null, evidence: [] }
    if (!forgotten) return base
    // ponytail: label suffix; real ghost styling when spec-4's forgotten-mode lands in GraphView
    return { ...base, salience: 0, label: `${n.label} (forgotten)` }
  })
  return { nodes, edges: snap.graph.edges }
}

export function GraphScrubber({ dir, sessions }: { dir: string; sessions: number }) {
  const [session, setSession] = useState(sessions - 1)
  const [snap, setSnap] = useState<EvalSnapshot | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .getEvalSnapshot(dir, session)
      .then((s) => {
        if (!cancelled) {
          setSnap(s)
          setMissing(false)
        }
      })
      .catch(() => {
        // 404 → older run without per-session snapshots; hide the scrubber.
        if (!cancelled) setMissing(true)
      })
    return () => {
      cancelled = true
    }
  }, [dir, session])

  if (missing || sessions <= 0) return null

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-xs text-zinc-500">
        <span className="font-mono text-zinc-600">session {session}</span>
        <input
          type="range"
          min={0}
          max={Math.max(0, sessions - 1)}
          value={session}
          onChange={(e) => setSession(Number(e.target.value))}
          className="flex-1"
        />
      </label>
      <div className="h-72 rounded border border-zinc-200">
        {snap && (
          <GraphView graph={toGraphResponse(snap)} flashIds={new Set()} onSelect={() => {}} />
        )}
      </div>
    </div>
  )
}
