"""Insights (read-only analytics) HTTP routes. Same handlers, same paths as
formerly in `app/main.py` — just a feature-owned home.

NB: auth-less like every route in this service (accepted demo posture).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from engram.app.deps import get_engram
from engram.insights import Insights
from engram.insights.schemas import (
    ActivityDay,
    ActivityResponse,
    Blocker,
    BlockersResponse,
    Hotspot,
    HotspotsResponse,
    InsightsSummary,
    MasteryTimelineResponse,
    ReviewItem,
    ReviewQueueResponse,
)

insights_router = APIRouter()


@insights_router.get("/insights/summary", response_model=InsightsSummary)
async def insights_summary(learner_id: str, eng=Depends(get_engram)):
    return InsightsSummary(**await Insights(eng.storage).summary(learner_id))


@insights_router.get("/insights/mastery-timeline", response_model=MasteryTimelineResponse)
async def insights_timeline(learner_id: str, node_ids: str | None = None,
                            eng=Depends(get_engram)):
    # drop blanks so "a,,b" or a trailing comma can't reach ANY($::uuid[]) as an
    # empty string (asyncpg would reject it -> 500); [] means "no ids" == None.
    ids = [s for s in node_ids.split(",") if s.strip()] if node_ids else None
    series = await Insights(eng.storage).mastery_timeline(learner_id, ids or None)
    return MasteryTimelineResponse(series=series)


@insights_router.get("/insights/hotspots", response_model=HotspotsResponse)
async def insights_hotspots(learner_id: str, k: int = 5, eng=Depends(get_engram)):
    return HotspotsResponse(
        hotspots=[Hotspot(**h) for h in await Insights(eng.storage).hotspots(learner_id, k)])


@insights_router.get("/insights/activity", response_model=ActivityResponse)
async def insights_activity(learner_id: str, days: int = 30, eng=Depends(get_engram)):
    return ActivityResponse(
        days=[ActivityDay(**d) for d in await Insights(eng.storage).activity(learner_id, days)])


@insights_router.get("/insights/review-queue", response_model=ReviewQueueResponse)
async def insights_review_queue(learner_id: str, k: int = 5, eng=Depends(get_engram)):
    return ReviewQueueResponse(
        items=[ReviewItem(**i) for i in await Insights(eng.storage).review_queue(learner_id, k)])


@insights_router.get("/insights/blockers", response_model=BlockersResponse)
async def insights_blockers(learner_id: str, eng=Depends(get_engram)):
    return BlockersResponse(
        blockers=[Blocker(**b) for b in await Insights(eng.storage).blockers(learner_id)])
