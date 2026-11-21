"""Run due jobs inside the request that queued them, for hosts with no long-lived process (JOBS_MODE=inline).

A serverless function may be frozen the moment its response has gone out, so a worker thread, or work
started after the response, may never finish. The middleware therefore runs `drain()` after the endpoint
has committed and *before* it releases the last byte of the response. The wait is bounded by a time and
a job budget, so a slow mock service cannot hold a citizen's request for long. Whatever is left (a job
waiting for a retry, or past the budget) is picked up by the next request or by the Vercel Cron call to
`GET /v1/admin/jobs/drain`.
"""

from __future__ import annotations

import time

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.jobs.service import run_pending

log = get_logger("rahat.jobs.inline")
WORKER_ID = "inline"


def drain(*, budget_seconds: float | None = None, max_jobs: int | None = None) -> int:
    """Run due jobs one at a time until none is due, the job cap is hit or the time budget is spent. Never raises."""
    settings = get_settings()
    budget = settings.jobs_inline_budget_seconds if budget_seconds is None else budget_seconds
    cap = settings.jobs_inline_max_jobs if max_jobs is None else max_jobs
    deadline = time.monotonic() + budget
    done = 0
    while done < cap and time.monotonic() < deadline:
        try:
            ran = run_pending(max_jobs=1, worker_id=WORKER_ID)
        except Exception:  # noqa: BLE001  (a database hiccup must not fail the citizen's request)
            log.exception("inline job drain stopped on an error")
            break
        if ran == 0:
            break
        done += ran
    return done
