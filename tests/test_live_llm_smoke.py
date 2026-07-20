"""Opt-in smoke test: real DashScope extraction. Skipped unless ENGRAM_LIVE_LLM=1
and DASHSCOPE_API_KEY is set. Not part of normal CI runs."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ENGRAM_LIVE_LLM") != "1",
    reason="set ENGRAM_LIVE_LLM=1 (and keys) to run the live extraction smoke",
)


async def test_real_extraction_returns_a_plan():
    from engram.adapters.llm.openai_compatible import build_llm
    from engram.app.config import Settings
    from engram.core.extraction import build_extraction_messages, parse_extraction
    from engram.core.models import LearningEvent

    settings = Settings()
    llm = build_llm(settings)
    events = [
        LearningEvent(learner_id="smoke", type="quiz_result",
                      text="Student correctly computed the derivative of x^2.",
                      signals={"correct": True})
    ]
    out = await llm.complete(
        "extractor", build_extraction_messages(events), schema={"type": "object"}
    )
    ex = parse_extraction(out.text or "")
    assert ex.nodes  # the model produced at least one concept
