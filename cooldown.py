import time
from typing import Generic, TypeVar

ID = TypeVar('ID')


class Cooldown(Generic[ID]):
    def __init__(self, time: float) -> None:
        self.time = time
        self._cache: dict[ID, float] = {}

    def _trigger(self, id: ID) -> float | None:
        l = self._cache.get((id))
        n = time.time()
        if l is not None:
            if n - l < self.time:
                # Limit exceeded
                return self.time - (n - l)
        self._cache[id] = n
        return None

    def __call__(self, id: ID) -> float | None:
        return self._trigger(id)
