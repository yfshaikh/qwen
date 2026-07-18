from engram.core.text import normalize_label


def test_normalize_label():
    assert normalize_label("  NMOS Transistors ") == "nmos transistor"
    assert normalize_label("EM-Induction!") == "em induction"
    assert normalize_label("gas") == "gas"          # short token: no depluralize
    assert normalize_label("Limits") == normalize_label("limit")


def test_canonical_label_abbreviation_loses_to_expansion():
    from engram.core.text import canonical_label
    assert canonical_label("EM Induction", "Electromagnetic Induction") == "Electromagnetic Induction"
    assert canonical_label("Electromagnetic Induction", "EM Induction") == "Electromagnetic Induction"
    assert canonical_label("Law", "Faraday's Law") == "Faraday's Law"
    assert canonical_label("AC", "Alternating Current") == "Alternating Current"


def test_canonical_label_ties_keep_current():
    from engram.core.text import canonical_label
    # same normalized shape -> stability, keep current
    assert canonical_label("Transistors", "transistor!") == "Transistors"
    assert canonical_label("Ohm's Law", "ohm law") == "Ohm's Law"


def test_canonical_label_empty_and_whitespace():
    from engram.core.text import canonical_label
    assert canonical_label("Flux", "") == "Flux"
    assert canonical_label("", "Flux") == "Flux"
    assert canonical_label("  ", "Magnetic Flux") == "Magnetic Flux"
