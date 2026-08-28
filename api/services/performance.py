from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


class HeavyJobQueueFull(RuntimeError):
    """Raised when a worker already has too many CPU-heavy requests waiting."""


class SupersededRequest(RuntimeError):
    """Raised when a newer request from the same browser supersedes this request."""


@dataclass(frozen=True)
class HeavyJobTicket:
    queue_ms: float


class HeavyJobController:
    """Bound CPU-heavy GIS work on small Vercel workers.

    FastAPI executes synchronous endpoints in a thread pool. Without an explicit
    limiter, several Shapely/Rasterio jobs can run concurrently and contend for
    the single vCPU normally available to a Hobby workload. This controller
    keeps the expensive section bounded and exposes small observability metrics.
    """

    def __init__(self) -> None:
        self.max_active = max(1, int(os.getenv("DTA_MAX_CONCURRENT_HEAVY_JOBS", "1")))
        self.max_waiting = max(0, int(os.getenv("DTA_MAX_QUEUED_HEAVY_JOBS", "4")))
        self.queue_timeout_s = max(0.1, float(os.getenv("DTA_HEAVY_JOB_QUEUE_TIMEOUT_S", "25")))
        self._semaphore = threading.BoundedSemaphore(self.max_active)
        self._lock = threading.Lock()
        self._active = 0
        self._waiting = 0
        self._completed = 0
        self._rejected = 0
        self._total_queue_ms = 0.0

    @contextmanager
    def slot(self) -> Iterator[HeavyJobTicket]:
        started = time.perf_counter()
        with self._lock:
            if self._active + self._waiting >= self.max_active + self.max_waiting:
                self._rejected += 1
                raise HeavyJobQueueFull("Antrean delineasi sedang penuh. Coba kembali beberapa saat lagi.")
            self._waiting += 1
        acquired = False
        try:
            acquired = self._semaphore.acquire(timeout=self.queue_timeout_s)
            queue_ms = (time.perf_counter() - started) * 1000.0
            with self._lock:
                self._waiting -= 1
                if not acquired:
                    self._rejected += 1
                else:
                    self._active += 1
                    self._total_queue_ms += queue_ms
            if not acquired:
                raise HeavyJobQueueFull("Waktu tunggu delineasi habis. Coba kembali beberapa saat lagi.")
            yield HeavyJobTicket(queue_ms=queue_ms)
        finally:
            if acquired:
                with self._lock:
                    self._active -= 1
                    self._completed += 1
                self._semaphore.release()

    def metrics(self) -> dict[str, int | float]:
        with self._lock:
            avg = self._total_queue_ms / self._completed if self._completed else 0.0
            return {
                "max_active": self.max_active,
                "max_waiting": self.max_waiting,
                "active": self._active,
                "waiting": self._waiting,
                "completed": self._completed,
                "rejected": self._rejected,
                "average_queue_ms": round(avg, 1),
            }


class LatestRequestRegistry:
    """Track only the newest delineation request from each browser session."""

    def __init__(self, max_clients: int = 2048) -> None:
        self.max_clients = max(64, int(max_clients))
        self._lock = threading.Lock()
        self._latest: OrderedDict[str, str] = OrderedDict()

    def register(self, client_id: str | None, request_id: str | None) -> tuple[str, str] | None:
        client = (client_id or "").strip()[:96]
        request = (request_id or "").strip()[:96]
        if not client or not request:
            return None
        with self._lock:
            self._latest[client] = request
            self._latest.move_to_end(client)
            while len(self._latest) > self.max_clients:
                self._latest.popitem(last=False)
        return client, request

    def is_current(self, token: tuple[str, str] | None) -> bool:
        if token is None:
            return True
        client, request = token
        with self._lock:
            return self._latest.get(client) == request

    def ensure_current(self, token: tuple[str, str] | None) -> None:
        if not self.is_current(token):
            raise SupersededRequest("Request delineasi digantikan oleh request yang lebih baru.")

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {"tracked_clients": len(self._latest), "max_clients": self.max_clients}


HEAVY_JOBS = HeavyJobController()
LATEST_REQUESTS = LatestRequestRegistry(
    max_clients=int(os.getenv("DTA_REQUEST_REGISTRY_MAX_CLIENTS", "2048"))
)
