from app.engine import evaluate_condition


def test_evaluate_numeric_comparisons():
    assert evaluate_condition(25.5, ">", 20)
    assert evaluate_condition("25.5", ">=", "25")
    assert not evaluate_condition(10, "<", 2)


def test_evaluate_equality_comparisons():
    assert evaluate_condition("1", "==", 1)
    assert evaluate_condition("ONLINE", "==", "ONLINE")
    assert evaluate_condition("OFFLINE", "!=", "ONLINE")
