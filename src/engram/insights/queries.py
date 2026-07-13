"""Pure aggregation over already-fetched storage data. No I/O, no LLM.
Averages over an empty set return None (absence of data != a real 0.0)."""
from __future__ import annotations

from datetime import datetime

from engram.core.models import Node


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize(nodes: list[Node], all_nodes: list[Node], edge_count: int,
              evidence_rows: list[dict], sessions: int,
              last_active: datetime | None) -> dict:
    masteries = [n.mastery for n in nodes if n.mastery is not None]
    confidences = [n.confidence for n in nodes if n.confidence is not None]
    # absent salience == "no decay signal yet" == NOT fading (matches review.py,
    # which uses 1.0 for None; the two modules must agree on cold-start nodes).
    fading = sum(1 for n in nodes
                 if (n.salience if n.salience is not None else 1.0) < 0.3)
    misconception_nodes = {r["node_id"] for r in evidence_rows if r["kind"] == "quiz_wrong"}
    return {
        "concepts": len(nodes),
        "edges": edge_count,
        "evidence": sum(r["count"] for r in evidence_rows),
        "avg_mastery": _avg(masteries),
        "avg_confidence": _avg(confidences),
        "forgotten": sum(1 for n in all_nodes if n.forgotten_at is not None),
        "fading": fading,
        # ponytail: proxy = live nodes with quiz_wrong evidence; true arc tracking
        # is misconception_arcs (deferred, no clean "open" audit signal).
        "open_misconceptions": len(misconception_nodes & {n.id for n in nodes}),
        "sessions": sessions,
        "last_active": last_active,
    }


def trend(history_rows: list[dict]) -> dict[str, str]:
    by_node: dict[str, list[dict]] = {}
    for r in history_rows:  # rows arrive ordered by ts
        by_node.setdefault(r["node_id"], []).append(r)
    out: dict[str, str] = {}
    for nid, rows in by_node.items():
        first, last = rows[0]["mastery"] or 0.0, rows[-1]["mastery"] or 0.0
        out[nid] = "improving" if last > first + 0.05 else "stuck"
    return out


def rank_hotspots(nodes: list[Node], evidence_rows: list[dict],
                  trend_by_node: dict[str, str], k: int) -> list[dict]:
    live = {n.id: n for n in nodes if n.id}  # skip id-less nodes (Hotspot.node_id is non-null)
    struggle: dict[str, int] = {}
    for r in evidence_rows:
        if r["kind"] in ("quiz_wrong", "struggle") and r["node_id"] in live:
            struggle[r["node_id"]] = struggle.get(r["node_id"], 0) + r["count"]
    ranked = sorted(struggle.items(), key=lambda kv: (-kv[1], live[kv[0]].label))
    return [{"node_id": nid, "label": live[nid].label, "struggle": cnt,
             "mastery": live[nid].mastery, "trend": trend_by_node.get(nid, "stuck")}
            for nid, cnt in ranked[:k]]


def timeline(history_rows: list[dict], label_by_id: dict[str, str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in history_rows:
        label = label_by_id.get(r["node_id"], r["node_id"])
        out.setdefault(label, []).append(
            {"ts": r["ts"], "mastery": r["mastery"], "confidence": r["confidence"]})
    return out
