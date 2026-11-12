"""python3 -m report <file.csv>"""

from __future__ import annotations

import sys
from pathlib import Path

from report.expenses import ReportError, by_month, read_expenses, summary


def main(argv: list[str]) -> int:
    paths = [a for a in argv if a != "--by-month"]
    if len(paths) != 1 or paths[0].startswith("--"):
        print("usage: python3 -m report <file.csv> [--by-month]", file=sys.stderr)
        return 2
    try:
        expenses = read_expenses(Path(paths[0]))
    except (OSError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(summary(expenses))
    if "--by-month" in argv and expenses:
        print(by_month(expenses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
