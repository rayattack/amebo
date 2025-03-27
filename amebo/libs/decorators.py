from functools import wraps


def emits(name: str, properties: dict = None):
    def decorator(decorated: any):
        @wraps(decorated)
        def delegate(*args, **kwargs):
            return decorated(*args, **kwargs)
    return decorator

