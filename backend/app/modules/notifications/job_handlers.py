"""Job kinds of the notifications module (discovered by app.modules.jobs)."""

from __future__ import annotations

from app.modules.notifications.service import SMS_JOB, deliver_sms, on_sms_failure

HANDLERS = {SMS_JOB: deliver_sms}
ON_FAILURE = {SMS_JOB: on_sms_failure}
