"""Engram — app-agnostic memory core for AI tutors."""

from __future__ import annotations

__all__ = ["Engram"]


def __getattr__(name: str):  # lazy export so partial builds import cleanly
    if name == "Engram":
        from engram.core.engram import Engram

        return Engram
    raise AttributeError(f"module 'engram' has no attribute {name!r}")
