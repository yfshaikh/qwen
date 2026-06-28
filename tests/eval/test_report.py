from engram.eval.report import headline, render_csv, render_markdown

ROWS = [
    {"recall_w_relevance": 0.4, "node_hit_rate": 0.5},
    {"recall_w_relevance": 0.6, "node_hit_rate": 1.0},
]

def test_render_markdown_has_header_and_marks_best():
    md = render_markdown(ROWS, target="node_hit_rate", best=ROWS[1])
    assert "| recall_w_relevance | node_hit_rate |" in md
    assert "⭐" in md
    assert md.count("\n") >= 3  # header + separator + 2 rows

def test_render_csv_roundtrips_headers():
    csv = render_csv(ROWS)
    assert csv.splitlines()[0] == "recall_w_relevance,node_hit_rate"
    assert "0.6,1.0" in csv

def test_headline_compares():
    line = headline({"re_explanation_rate": 0.1, "preference_honored_rate": 0.9},
                    {"re_explanation_rate": 0.6, "preference_honored_rate": 0.3})
    assert "re-explan" in line.lower()
    assert "0.1" in line and "0.6" in line
