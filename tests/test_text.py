from engram.core.text import normalize_label, token_jaccard


def test_normalize_label():
    assert normalize_label("  NMOS Transistors ") == "nmos transistor"
    assert normalize_label("EM-Induction!") == "em induction"
    assert normalize_label("gas") == "gas"          # short token: no depluralize
    assert normalize_label("Limits") == normalize_label("limit")


def test_token_jaccard_identical_and_disjoint():
    assert token_jaccard("EM Induction", "em induction") == 1.0
    assert token_jaccard("Ohm's Law", "Faraday flux") == 0.0


def test_token_jaccard_partial_overlap():
    # {em, induction} vs {electromagnetic, induction} -> 1/3
    assert abs(token_jaccard("EM induction", "electromagnetic induction") - 1 / 3) < 1e-9


def test_token_jaccard_empty_is_zero():
    assert token_jaccard("", "anything") == 0.0
    assert token_jaccard("!!!", "???") == 0.0
