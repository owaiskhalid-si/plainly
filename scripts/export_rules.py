"""Write site/rules.json from the rule registry, so the site's rule catalogue never drifts
from the code. CI checks the two match."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from plainly.cli import rules_json  # noqa: E402
from plainly.engine import active_rules  # noqa: E402


def main() -> int:
    on = {r.id for r in active_rules()}
    target = ROOT / "site" / "rules.json"
    target.write_text(json.dumps(rules_json(on), indent=2) + "\n", "utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({len(on)} rules on)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
