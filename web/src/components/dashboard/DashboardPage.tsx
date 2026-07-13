import { useEffect, useState } from 'react'
import * as api from '../../api'
import { GraphView } from '../GraphView'
import type { ActivityDay, Blocker, GraphResponse, Hotspot, InsightsSummary, MasteryPoint, ReviewItem } from '../../types'
import { ActivityStrip } from './ActivityStrip'
import { HotspotBars } from './HotspotBars'
import { MasteryChart } from './MasteryChart'
import { ReviewQueueCard } from './ReviewQueueCard'
import { StatTiles } from './StatTiles'

interface DashboardData {
  summary: InsightsSummary
  timeline: Record<string, MasteryPoint[]>
  hotspots: Hotspot[]
  activity: ActivityDay[]
  reviewQueue: ReviewItem[]
  blockers: Blocker[]
}

export function DashboardPage({ learnerId, graph }: { learnerId: string; graph: GraphResponse }) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    Promise.all([
      api.getInsightsSummary(learnerId),
      api.getMasteryTimeline(learnerId),
      api.getHotspots(learnerId),
      api.getActivity(learnerId),
      api.getReviewQueue(learnerId),
      api.getBlockers(learnerId),
    ])
      .then(([summary, timeline, hotspots, activity, reviewQueue, blockers]) => {
        if (cancelled) return
        setData({ summary, timeline, hotspots, activity, reviewQueue, blockers })
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [learnerId])

  // ponytail: wiring the suggested opening line into the transcript panel is
  // out of scope for this task — stub with a console.log for now.
  function onAsk(item: ReviewItem) {
    console.log('ask the tutor about', item)
  }

  if (error) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center bg-zinc-50">
        <p className="text-sm text-rose-600">Failed to load dashboard: {error}</p>
      </main>
    )
  }

  if (!data) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center bg-zinc-50">
        <p className="text-sm text-zinc-400">Loading dashboard…</p>
      </main>
    )
  }

  const blockerIds = new Set(data.blockers.map((b) => b.node_id))

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-zinc-50 p-4">
      <StatTiles summary={data.summary} />

      <section className="rounded-lg border border-zinc-200 bg-white p-3">
        <h2 className="mb-2 text-xs font-semibold text-zinc-700">Mastery over time</h2>
        <MasteryChart series={data.timeline} />
      </section>

      <section className="rounded-lg border border-zinc-200 bg-white p-3">
        <h2 className="mb-2 text-xs font-semibold text-zinc-700">Review queue</h2>
        <ReviewQueueCard items={data.reviewQueue} onAsk={onAsk} />
      </section>

      <section className="rounded-lg border border-zinc-200 bg-white p-3">
        <h2 className="mb-2 text-xs font-semibold text-zinc-700">Struggle hotspots</h2>
        <HotspotBars hotspots={data.hotspots} />
      </section>

      <section className="h-[420px] overflow-hidden rounded-lg border border-zinc-200 bg-white">
        <GraphView graph={graph} flashIds={new Set()} onSelect={() => {}} highlightIds={blockerIds} />
      </section>

      <section className="rounded-lg border border-zinc-200 bg-white p-3">
        <h2 className="mb-2 text-xs font-semibold text-zinc-700">Activity</h2>
        <ActivityStrip days={data.activity} />
      </section>
    </main>
  )
}
