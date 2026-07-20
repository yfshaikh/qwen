"""Inline tags that let the voice tutor drive the whiteboard + clicky pointer
mid-turn, with zero extra LLM rounds (the tutor embeds tags in its reply text;
the pipeline strips them and turns them into WS events)."""
