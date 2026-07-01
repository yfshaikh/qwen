# Known issues / rough edges

Observed from the `demo-8334427e` trace (2026-06-27). None are bugs — recall
and consolidation work as designed — but each is a real quality gap worth
tracking. Ordered roughly by impact.

## 1. One-cycle recall lag
The tutor's memory only reflects the graph as of the **last consolidation**.
Events from the current, un-consolidated turns are invisible to recall until
the next Keeper run. In the trace, turn 8 told the learner they were "already
strong" on Limits because the failed quiz (turn 7) hadn't been consolidated
yet; turn 9 (post-consolidate) correctly saw `mastery=0.06`.

**Why:** by design — chat never mutates the graph; only `consolidate()` does.
**Possible fix:** fold pending-event signal into recall, or auto-consolidate
on a turn cadence. Either erodes the clean online/offline split — decide
deliberately.

## 2. Tutor doesn't act on low-mastery nodes
Recall correctly surfaced `Limit mastery=0.06` at turn 9, yet the tutor moved
on to the Power Rule instead of remediating limits. Recall did its job; the
**tutor prompt** has no instruction to prioritize weak nodes.
**Fix:** add a directive to the tutor system prompt to target low-mastery
recalled concepts first. Cheap, prompt-only.

## 3. Ranking runs on recency + relevance only
`salience` is ~1.0 on nearly every node (decay hasn't engaged on a short
session) and `importance` is `null` everywhere (the extractor never emits a
numeric importance). So two of the three scoring terms are inert; ranking is
effectively recency + vector relevance.
**Fix:** have the extractor emit `importance`, and/or tune decay so salience
differentiates. Eval-gated (see MVP spec §11.2).

## 4. Preference over-attribution from tutor speech
Both `utterance` and `tutor_explanation` events feed the extractor, so the
tutor's own words can mint "learner" nodes. In the trace, "Understanding
intuition over memorization" was extracted from the tutor saying "you don't
need to memorize," not from the learner.
**Fix:** weight or scope extraction so learner preferences come from
`utterance` events; let `tutor_explanation` inform concepts but not
preferences/goals.

## 5. Redundant inverse edges
Limit↔Continuity carries both a `relates_to` and a `prerequisite` edge, one
added per consolidation. Harmless but duplicative.
**Fix:** dedupe edges by `(source, target)` pair in the Keeper's link step,
preferring the stronger relation type.

## 6. Duplicate / near-duplicate concept nodes  (genuine bug)
The Keeper's merge step doesn't reliably collapse semantically similar concepts,
so the graph accumulates near-duplicate nodes across sessions — the same concept
re-extracted under a slightly different label (e.g. "NMOS Transistor" vs "NMOS
device", or a concept appearing twice). Surfaced directly in Marfini's
knowledge-map UI as redundant concept cards. Unlike #1–#5 this is a real defect,
not just a tuning gap.
**Why:** merge dedups candidates by embedding cosine against
`keeper_tau_high`/`keeper_tau_low`; if the threshold is too strict, or the
extractor labels the same concept differently run-to-run, distinct nodes survive
instead of merging into one. (Surfaced via Marfini integration; the fix is
Engram-side, in the Keeper.)
**Fix:** normalize labels (case/whitespace/light stemming) before the embedding
compare, lower/tune the merge threshold, and/or add a canonicalization pass that
merges on combined lexical + embedding similarity. Eval-gate the change so
loosening doesn't over-merge genuinely distinct concepts.
