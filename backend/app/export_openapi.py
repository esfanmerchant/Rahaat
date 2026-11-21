"""Write the OpenAPI document to backend/openapi.json. The frontend generates its typed client from it.

    uv run python -m app.export_openapi
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    from app.main import create_app

    target = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "openapi.json"
    document = create_app().openapi()
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {target} ({len(document.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
