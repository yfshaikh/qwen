"""Whiteboard SVG-diagram generation (voice/clicky feature).

The tutor draws a labelled SVG diagram on demand; each labelled part carries a
`data-clicky="src-<name>"` anchor so the on-screen "clicky" cursor can point at
sub-parts of the rendered panel. Generation is one LLM call routed to a GLM
model on the same DashScope client as the rest of Engram (role "diagram").
"""
