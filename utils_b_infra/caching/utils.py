import hashlib
from typing import Any, Callable, Dict, Tuple


def key_builder(
        func: Callable[..., Any],
        app_space: str,
        namespace: str,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any]
) -> str:
    kwargs_copy = kwargs.copy()
    sorted_kwargs = tuple(sorted(kwargs_copy.items()))

    key_str = f"{func.__name__}:{args}:{sorted_kwargs}"
    key_hash = hashlib.md5(key_str.encode()).hexdigest()
    key = f"{app_space}:{namespace}:{key_hash}"
    return key
