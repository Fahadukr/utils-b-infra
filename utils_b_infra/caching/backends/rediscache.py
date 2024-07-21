from redis import Redis
from redis.connection import ConnectionPool
from utils_b_infra.caching.backends.base import BaseCache


class RedisCache(BaseCache):
    def __init__(self,
                 url: str = None,
                 host: str = None,
                 port: int = None,
                 password: str = None,
                 db: int = 0,
                 app_space: str | None = "",
                 default_timeout: int | None = 300) -> None:

        if not url and not host:
            raise ValueError("Either url or host, port and password must be provided")
        if url:
            self._redis = Redis(connection_pool=ConnectionPool.from_url(url=url))
        else:
            self._redis = Redis(connection_pool=ConnectionPool(host=host, port=port, password=password, db=db))
        self._app_space = app_space
        self._default_timeout = default_timeout

    def get_with_ttl(self, key: str) -> tuple[int, bytes | None]:
        with self._redis.pipeline() as pipe:
            ttl, value = pipe.ttl(key).get(key).execute()
            return ttl, value

    def get(self, key: str) -> bytes | None:
        return self._redis.get(key)

    def set(self, key: str, value: bytes, expire: int = None) -> None:
        """
        Set expire to 0 to make it never expire
        """
        self._redis.set(key, value, ex=expire if expire is not None else self._default_timeout)

    def clear(self, namespace: str = None, key: str = None) -> int:
        if key:
            return self._redis.delete(key)

        pattern = ""
        if self._app_space:
            pattern += f"{self._app_space}:"
        if namespace:
            pattern += f"{namespace}:"
        pattern += "*"

        lua = f"""
        local keys = redis.call('KEYS', '{pattern}')
        for i = 1, #keys, 5000 do
            redis.call('DEL', unpack(keys, i, math.min(i + 4999, #keys)))
        end
        return #keys
        """
        return self._redis.eval(lua, numkeys=0)
