"""Short-lived, per-worker caches for shared public catalog reads."""

from threading import Lock
from time import monotonic
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class PublicReadCache(Generic[T]):
    """Coalesce concurrent loads; failed reads are never cached.

    Values must be treated as read-only. Checkout always reads live database prices.
    """

    def __init__(self, ttl_seconds: float = 30):
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._expires_at = 0.0
        self._value: T | None = None

    def get(self, loader: Callable[[], T]) -> T:
        with self._lock:
            if self._value is None or monotonic() >= self._expires_at:
                value = loader()
                self._value = value
                self._expires_at = monotonic() + self.ttl_seconds
            return self._value

    def invalidate(self) -> None:
        with self._lock:
            self._expires_at = 0.0


catalog_cache = PublicReadCache()
brand_cache = PublicReadCache()
