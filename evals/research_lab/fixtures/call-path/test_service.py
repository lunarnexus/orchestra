from service import handle_request


def test_greeting():
    assert handle_request({'name': '  ada '}) == 'Hello, Ada!'
