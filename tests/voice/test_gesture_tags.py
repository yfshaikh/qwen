"""GestureTagParser: stream-safe extraction of inline draw/gesture tags."""

from engram.voice.clicky.tags import GestureTagParser


def _feed_all(chunks):
    p = GestureTagParser()
    text, events = "", []
    for c in chunks:
        t, evs = p.feed(c)
        text += t
        events += evs
    text += p.flush()
    return text, events


def test_gesture_tag_stripped_and_parsed():
    text, events = _feed_all(["The gate [point:src-gate] is here."])
    assert "[" not in text and "point" not in text
    assert text == "The gate  is here."
    assert events == [{"kind": "gesture", "gesture": "point", "anchor": "src-gate",
                       "note": "", "_at": 9}]


def test_all_anchor_families_and_gestures():
    _, events = _feed_all([
        "[point:panel-current] [circle:panel-2] [underline:src-a] "
        "[arrow:src-b] [show:panel-3]"
    ])
    kinds = [(e["gesture"], e["anchor"]) for e in events]
    assert kinds == [
        ("point", "panel-current"), ("circle", "panel-2"),
        ("underline", "src-a"), ("arrow", "src-b"), ("show", "panel-3"),
    ]


def test_note_is_captured_and_truncated():
    _, events = _feed_all(["[circle:panel-current:the whole diagram]"])
    assert events[0]["note"] == "the whole diagram"
    _, ev2 = _feed_all(["[point:src-x:" + "z" * 60 + "]"])
    assert len(ev2[0]["note"]) == 40


def test_malformed_anchor_is_dropped_but_text_removed():
    # Unknown anchor families (section-*, bogus) are removed from the spoken
    # text but produce no gesture.
    text, events = _feed_all(["Look [point:section-1] and [point:nonsense] here."])
    assert events == []
    assert "[" not in text and "section" not in text and "nonsense" not in text
    assert text == "Look  and  here."


def test_unknown_verb_is_left_intact():
    # Not a known verb -> not a tag -> left in the text untouched.
    text, events = _feed_all(["An array a[i:j] slice."])
    assert events == []
    assert text == "An array a[i:j] slice."


def test_tag_split_across_chunks():
    text, events = _feed_all(["The gate [poi", "nt:src-ga", "te] sits."])
    assert text == "The gate  sits."
    assert [(e["gesture"], e["anchor"]) for e in events] == [("point", "src-gate")]


def test_draw_tag_with_anchor_declarations():
    text, events = _feed_all([
        "[draw: cross-section of an NMOS | src-gate=the metal gate; "
        "src-channel=the inversion channel] Here it is."
    ])
    assert text == " Here it is."
    assert len(events) == 1
    d = events[0]
    assert d["kind"] == "draw"
    assert d["intent"] == "cross-section of an NMOS"
    assert d["anchors"] == {"src-gate": "the metal gate",
                            "src-channel": "the inversion channel"}


def test_draw_tag_without_anchors():
    _, events = _feed_all(["[draw: a right triangle]"])
    assert events[0]["kind"] == "draw"
    assert events[0]["intent"] == "a right triangle"
    assert events[0]["anchors"] == {}


def test_draw_split_across_chunks_holds_until_complete():
    p = GestureTagParser()
    t1, e1 = p.feed("[draw: nmos | src-gate=the ga")
    # Mid-tag: nothing released, nothing parsed yet.
    assert t1 == "" and e1 == []
    t2, e2 = p.feed("te] done.")
    assert t2 == " done."
    assert e2[0]["anchors"] == {"src-gate": "the gate"}


def test_flush_releases_trailing_non_tag_fragment():
    p = GestureTagParser()
    t1, _ = p.feed("almost a tag [po")
    assert t1 == "almost a tag "  # holds "[po" (prefix of point)
    # Stream ends without closing it -> flush spits it back out.
    assert p.flush() == "[po"
