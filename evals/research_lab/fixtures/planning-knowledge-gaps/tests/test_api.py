from src.api import get_report


def test_report():
    assert 'rows' in get_report()
