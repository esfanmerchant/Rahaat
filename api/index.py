"""Vercel entry point: the whole FastAPI app as one Python function.

Prototype. Not an official service. All identity, payment and data services are simulated.

`vercel.json` rewrites /v1/*, /healthz, /readyz, /docs, /redoc and /openapi.json to this file; the built
frontend is served by the CDN. The backend package lives in ../backend, so put it on the import path.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402  (the path above must be set first)

__all__ = ["app"]
