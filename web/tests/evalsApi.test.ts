import { describe, expect, it, vi, afterEach } from 'vitest'
import { getEvalRuns, launchEvalRun } from '../src/api'

afterEach(() => vi.unstubAllGlobals())

describe('eval api client', () => {
  it('unwraps runs and posts launches', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [{ run_id: 'r1', status: 'passed' }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ run_id: 'r2', dir: 'scn-r2' }) })
    vi.stubGlobal('fetch', fetchMock)
    expect((await getEvalRuns())[0].run_id).toBe('r1')
    const launched = await launchEvalRun('calc-mastery', 0.5)
    expect(launched.dir).toBe('scn-r2')
    const [url, opts] = fetchMock.mock.calls[1]
    expect(url).toBe('/eval/runs')
    expect(JSON.parse(opts.body)).toEqual({ scenario_id: 'calc-mastery', budget_usd: 0.5 })
  })

  it('throws on http error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409 }))
    await expect(launchEvalRun('x')).rejects.toThrow('409')
  })
})
