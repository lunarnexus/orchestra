from .store import save


def run(job):
    save(job)
    return {'ok': True}
