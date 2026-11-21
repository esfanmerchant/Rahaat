"""Job kinds of the payments module (discovered by app.modules.jobs)."""

from __future__ import annotations

from app.modules.payments.service import RELEASE_JOB, on_release_failure, release_job

HANDLERS = {RELEASE_JOB: release_job}
ON_FAILURE = {RELEASE_JOB: on_release_failure}
