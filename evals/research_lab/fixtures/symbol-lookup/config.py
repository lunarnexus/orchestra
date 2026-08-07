def parse_limit(value, default=10):
    if value is None:
        return default
    return int(value)
