from engram.core.text import normalize_label


def test_normalize_label():
    assert normalize_label("  NMOS Transistors ") == "nmos transistor"
    assert normalize_label("EM-Induction!") == "em induction"
    assert normalize_label("gas") == "gas"          # short token: no depluralize
    assert normalize_label("Limits") == normalize_label("limit")
