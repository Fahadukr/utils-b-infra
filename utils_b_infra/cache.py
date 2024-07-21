import logging
import warnings
from functools import wraps
from typing import Callable, get_type_hints

from utils_b_infra.caching import BaseCache, CacheConfig, key_builder

__all__ = ["Cache", "CacheConfig"]

logger: logging.Logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def get_typed_return_annotation(func) -> type | None:
    """
    Returns the type annotations of the given function.

    Parameters:
    func (function): The function whose type annotations are to be retrieved.

    Returns:
    type: The type annotations of the given function.
    """
    return_type = get_type_hints(func)
    return return_type.get('return')


class Cache:
    def __init__(self, config: CacheConfig = CacheConfig()) -> None:
        self._config = config
        self._coder = self._config.coder
        self._backend_cache = self._get_cache_backend()

    def _get_cache_backend(self) -> BaseCache:
        cache_type = self._config.cache_type
        if cache_type == 'SimpleCache':
            warnings.warn("SimpleCache is not recommended for production environment with multiple workers.")
            from utils_b_infra.caching.backends import SimpleCache
            return SimpleCache(
                threshold=self._config.simple_cache_threshold,
                default_timeout=self._config.default_timeout
            )

        if cache_type == 'RedisCache':
            from utils_b_infra.caching.backends import RedisCache
            return RedisCache(
                url=self._config.redis_url,
                host=self._config.redis_host,
                port=self._config.redis_port,
                password=self._config.redis_password,
                db=self._config.redis_db,
                app_space=self._config.app_space,
                default_timeout=self._config.default_timeout
            )

        if cache_type == 'MongoCache':
            from utils_b_infra.caching.backends import MongoCache
            return MongoCache(
                url=self._config.mongo_url,
                database=self._config.mongo_database,
                collection=self._config.mongo_collection,
                direct_connection=self._config.mongo_direct_connection,
                app_space=self._config.app_space,
                default_timeout=self._config.default_timeout
            )

    def _get_is_sliding_expiration(self, endpoint_sliding_expiration: bool | None) -> bool:
        """
        Check if the endpoint has sliding expiration enabled, if yes, return its value over the global config.
        """
        if endpoint_sliding_expiration is None and self._config.sliding_expiration:
            return True
        return endpoint_sliding_expiration or False

    def cached(self,
               timeout: int = None,
               sliding_expiration: bool = None,
               namespace: str = "") -> Callable[[Callable], Callable]:
        """
        Decorator to cache the result of a function.
        :param timeout : Timeout in seconds (int).
                  Set to `0` to never expire. If not specified, the default timeout from the cache config is used.
                  A pre-calculated values in the cache_config can be used, e.g., `cache_config.ONE_HOUR`,
                  `cache_config.ONE_DAY`, etc.
        :param sliding_expiration : Enable sliding expiration for the cache key (bool).
                  sliding window expiration mechanism resets the expiration time on every access
                  to the cache key, this means that the cache key will only expire if it is not accessed
                  for the duration of the timeout.

                  * sliding_expiration at the endpoint level takes precedence over the global config.

        :param namespace: Namespace for the cache keys.
        """

        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Key building and sliding expiration logic stays the same
                is_sliding_expiration = self._get_is_sliding_expiration(sliding_expiration)
                key = key_builder(
                    func,
                    app_space=self._config.app_space,
                    namespace=namespace,
                    args=args,
                    kwargs=kwargs
                )

                # Try to retrieve the cache
                try:
                    ttl, cached_result = self.get_with_ttl(key)
                except Exception as e:
                    logger.warning(
                        f"Error retrieving cache key '{key}' from backend: {e}",
                        exc_info=True,
                    )
                    ttl, cached_result = 0, None

                if cached_result is not None:  # Cache hit
                    result = self._coder.decode(cached_result)
                    if is_sliding_expiration:
                        self.set(key, cached_result, timeout)
                else:  # Cache miss
                    result = func(*args, **kwargs)
                    result_encoded = self._coder.encode(result)
                    self.set(key, result_encoded, timeout)

                return result

            return wrapper

        return decorator

    def get_with_ttl(self, key: str) -> tuple[int, bytes | None]:
        return self._backend_cache.get_with_ttl(key)

    def get(self, key: str) -> bytes | None:
        return self._backend_cache.get(key)

    def set(self, key: str, value: bytes, expire: int = None) -> None:
        self._backend_cache.set(key, value, expire)

    def clear(self, namespace: str = None, key: str = None) -> int:
        return self._backend_cache.clear(namespace, key)
