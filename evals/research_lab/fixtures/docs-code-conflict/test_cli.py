from cli import mode


def test_default_mode():
    assert mode() == 'fast'
