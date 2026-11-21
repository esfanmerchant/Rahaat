"""Functions owned by other tracks, imported at call time so this module works before they exist.

Each path is the one listed in `app/contracts/engine.py`. When an import fails the caller degrades safely
(a person will check, a human reviews); it never invents a result. Tests put fakes in `sys.modules`.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, Final

from app.core.logging import get_logger

log = get_logger("rahat.applications.hooks")

DECIDE_AND_RECORD: Final = ("app.modules.decision.service", "decide_and_record")
USER_VIEW: Final = ("app.modules.decision.service", "user_view")
CHECK_DOCUMENT: Final = ("app.modules.docs_ai.service", "check_document")
VERIFY_IDENTITY: Final = ("app.modules.integrations.service", "verify_identity")
LOOKUP_REGISTRY: Final = ("app.modules.integrations.service", "lookup_registry")
OPEN_CASE: Final = ("app.modules.cases.service", "open_case")
REQUEST_PAYMENT: Final = ("app.modules.payments.service", "request_payment")
NOTIFY: Final = ("app.modules.notifications.service", "notify")

_warned: set[str] = set()


def optional(target: tuple[str, str]) -> Callable[..., Any] | None:
    """The function, or None when its module is not installed in this build."""
    module_name, attr = target
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        if module_name not in _warned:
            _warned.add(module_name)
            log.warning("optional module %s is not available; degrading safely", module_name)
        return None
    except Exception:  # noqa: BLE001  (a module that breaks while importing must not break this request)
        log.exception("optional module %s failed to import; degrading safely", module_name)
        return None
    fn = getattr(module, attr, None)
    if not callable(fn):
        key = f"{module_name}.{attr}"
        if key not in _warned:
            _warned.add(key)
            log.warning("optional function %s is missing; degrading safely", key)
        return None
    return fn
