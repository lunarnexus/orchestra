from src.api import handle


def test_flow():
    assert handle({'id': 1}) == {'ok': True}
