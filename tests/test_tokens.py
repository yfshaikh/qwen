from engram.core.tokens import TokenCounter, heuristic_token_count


def test_counts_scale_with_length():
    assert heuristic_token_count("") >= 1  # never zero, simplifies budget math
    short = heuristic_token_count("a")
    longer = heuristic_token_count("a" * 40)
    assert longer > short


def test_roughly_chars_over_four():
    # 40 chars -> ~10 tokens (len+3)//4
    assert heuristic_token_count("a" * 40) == 10


def test_token_counter_type_is_callable_alias():
    fn: TokenCounter = heuristic_token_count
    assert fn("hello world") >= 1
