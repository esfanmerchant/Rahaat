"""Job kinds of the webhooks module (discovered by app.modules.jobs)."""

from __future__ import annotations

from app.modules.webhooks.emit import DELIVER_JOB
from app.modules.webhooks.service import deliver_job

HANDLERS = {DELIVER_JOB: deliver_job}
