from formatting import greeting


def handle_request(payload):
    return greeting(payload['name'])
