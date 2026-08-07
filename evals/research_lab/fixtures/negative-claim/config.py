import json


def load(path):
    return json.loads(path.read_text())
