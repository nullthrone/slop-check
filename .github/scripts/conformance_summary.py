"""Print a Markdown summary of a ``slopcheck-dev conformance`` result file.

    python .github/scripts/conformance_summary.py RESULT.json >> "$GITHUB_STEP_SUMMARY"

Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.0f} %"


def render(result: dict) -> str:
    lines = ["## Skill conformance", ""]
    lines.append(f"Run at {result.get('run_at', '?')}.")
    lines.append("")
    lines += [
        "| Model | Passed | Recall | Precision | Verdicts | Rewrites | Parse failures | USD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model in result.get("models") or []:
        s = model.get("summary") or {}
        name = model.get("canonical_slug") or model.get("id")
        lines.append(
            f"| `{name}` | {s.get('passed', 0)}/{s.get('cases', 0)} "
            f"| {pct(s.get('recall'))} | {pct(s.get('precision'))} | {pct(s.get('verdict_accuracy'))} "
            f"| {pct(s.get('rewrite_pass_rate'))} | {s.get('parse_failures', 0)} | {s.get('usd', 0):.4f} |"
        )
    notices = result.get("notices") or []
    if notices:
        lines += ["", "Notices:", ""] + [f"- {n}" for n in notices]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    result = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
