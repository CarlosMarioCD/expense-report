"""python3 -m report <file.csv>"""

from __future__ import annotations

import sys
from pathlib import Path

from report.expenses import ReportError, format_monthly, read_expenses, summary


def main(argv: list[str]) -> int:
    paths = [a for a in argv if a != "--by-month"]
    by_month = len(paths) < len(argv)
    if len(paths) != 1 or len(argv) - len(paths) > 1 or paths[0].startswith("--"):
        print("usage: python3 -m report <file.csv> [--by-month]", file=sys.stderr)
        return 2
    try:
        expenses = read_expenses(Path(paths[0]))
    except (OSError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_monthly(expenses) if by_month else summary(expenses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
