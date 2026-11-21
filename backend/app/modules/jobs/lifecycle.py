"""Start the background job worker with the app, when `worker_enabled_effective` (off in tests)."""

from __future__ import annotations

import threading
import uuid

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("rahat.jobs.worker")

POLL_SECONDS = 1.0
ERROR_PAUSE_SECONDS = 5.0


class Worker(threading.Thread):
    def __init__(self, poll_seconds: float = POLL_SECONDS) -> None:
        super().__init__(name="rahat-job-worker", daemon=True)
        self.poll_seconds = poll_seconds
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self.stop_event = threading.Event()

    def run(self) -> None:
        from app.modules.jobs.service import run_pending

        log.info("job worker %s started", self.worker_id)
        while not self.stop_event.is_set():
            try:
                done = run_pending(max_jobs=25, worker_id=self.worker_id)
            except Exception:  # noqa: BLE001  (a database hiccup must not end the loop)
                log.exception("job worker loop error; pausing")
                self.stop_event.wait(ERROR_PAUSE_SECONDS)
                continue
            if done == 0:
                self.stop_event.wait(self.poll_seconds)
        log.info("job worker %s stopped", self.worker_id)


_worker: Worker | None = None


def startup() -> None:
    global _worker
    if not get_settings().job_thread_enabled or _worker is not None:
        return
    _worker = Worker()
    _worker.start()


def shutdown() -> None:
    global _worker
    if _worker is None:
        return
    _worker.stop_event.set()
    _worker.join(timeout=10)
    _worker = None
