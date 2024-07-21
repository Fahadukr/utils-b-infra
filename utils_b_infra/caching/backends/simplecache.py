import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Tuple

import time
from utils_b_infra.caching.backends.base import BaseCache


@dataclass
class Value:
    """
    A data class for storing cached data along with its expiration timestamp.

    Attributes:
        data (bytes): The cached data.
        ttl_ts (int): The time-to-live expiration timestamp of the cached data.
    """
    data: bytes
    ttl_ts: int


class SimpleCache(BaseCache):
    """
    A simple in-memory caching backend using an LRU eviction strategy.

    This cache backend is designed for single-process environments and is not intended
    for use in production due to its lack of thread safety in highly concurrent scenarios.
    """

    def __init__(self, threshold: int = 100, default_timeout: int = 300):
        """
        Initializes the cache with a given threshold and default timeout.

        Parameters:
            threshold (int): The maximum number of items to store before eviction.
            default_timeout (int): The default time-to-live (TTL) for each cache item, in seconds.
        """
        self._store = OrderedDict()  # Preserve the order of insertion for LRU logic
        self._lock = threading.Lock()
        self._threshold = threshold
        self._default_timeout = default_timeout

    @property
    def _now(self) -> int:
        """Returns the current time in seconds since the epoch."""
        return int(time.time())

    def _get(self, key: str) -> Optional[Value]:
        """Retrieves an item from the cache if it exists and is not expired."""
        if key in self._store:
            self._store.move_to_end(key)  # Accessing the item moves it to the end (LRU)
            v = self._store[key]
            if v.ttl_ts < self._now:
                del self._store[key]
                return None
            return v
        return None

    def get_with_ttl(self, key: str) -> Tuple[int, Optional[bytes]]:
        with self._lock:
            v = self._get(key)
            if v:
                return v.ttl_ts - self._now, v.data
            return 0, None

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            v = self._get(key)
            if v:
                return v.data
            return None

    def set(self, key: str, value: bytes, expire: Optional[int] = None) -> None:
        """
        Sets the value in the cache with an optional expiration time.

        Parameters:
            key (str): The key under which to store the data.
            value (bytes): The data to store.
            expire (Optional[int]): The expiration time in seconds; uses default timeout if not specified.
        """
        with self._lock:
            if len(self._store) >= self._threshold:
                self._store.popitem(last=False)  # Remove oldest item - Least Recently Used (LRU)
            ttl = self._now + (expire if expire is not None else self._default_timeout)
            self._store[key] = Value(data=value, ttl_ts=ttl)
            self._store.move_to_end(key)

    def clear(self, namespace: Optional[str] = None, key: Optional[str] = None) -> int:
        """
        Clears items from the cache based on the specified namespace or key.

        Parameters:
            namespace (Optional[str]): The namespace to clear.
            key (Optional[str]): The specific key to clear.

        Returns:
            int: The number of items cleared from the cache.
        """
        count = 0
        with self._lock:
            if key:
                if key in self._store:
                    del self._store[key]
                    count += 1
            else:
                if namespace:
                    keys_to_remove = [k for k in self._store if k.startswith(namespace)]
                    for k in keys_to_remove:
                        del self._store[k]
                        count += 1
                else:
                    count = len(self._store)
                    self._store.clear()
            return count

    def size(self) -> int:
        """Returns the current number of items in the cache."""
        with self._lock:
            return len(self._store)
