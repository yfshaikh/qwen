import type { AuditRow, ConsolidateReport } from '../types'

export function KeeperTrace({
  report,
  rows,
  error,
}: {
  report: ConsolidateReport | null
  rows: AuditRow[]
  error?: string
}) {
  if (error) return <div className="trace error">⚠️ {error}</div>
  if (!report)
    return <div className="trace empty">Consolidate to see the Keeper turn events into memory.</div>
  if (report.skipped)
    return <div className="trace empty">Nothing to consolidate (no pending events / run in progress).</div>
  return (
    <div className="trace">
      <div className="trace-head">
        nodes +{report.nodes_created} · edges +{report.edges_created} · updated {report.nodes_updated} ·
        merged {report.merged} · forgotten {report.forgotten} · processed {report.processed_events}
      </div>
      <ul className="trace-rows">
        {rows.map((r) => (
          <li key={r.id}>
            <b>{r.op}</b>
            {r.rationale ? ` — ${r.rationale}` : ''}
          </li>
        ))}
      </ul>
    </div>
  )
}
