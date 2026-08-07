from retry import attempts


def test_attempts():
    assert attempts() == 4
