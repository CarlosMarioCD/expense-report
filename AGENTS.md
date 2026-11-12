# Expense report

A small command-line report over a CSV of expenses: `python3 -m report data/sample.csv`.
Standard library only.

## Commands
- Test: the TEST_CMD in factory.conf (must pass before any PR). There is no linter.

## Conventions
- Python 3.10+. Nothing outside the standard library is installed.
- Money is `Decimal`, never float. Dates are `datetime.date`.
- Every behaviour change gets a unittest in `tests/`, written BEFORE the implementation.
- Keep functions under 30 lines. Parsing lives in `report/expenses.py`, printing in `report/__main__.py`.
- Keep the whole change under 150 lines added+removed (a gate rejects over 200). Write compact code and few, focused tests. For multi-format input use only the standard library (csv, json, zipfile + xml.etree for .xlsx).
- Bad input raises `ReportError` naming the line; the CLI prints it and exits 1.

## Factory rules
- Phase state lives in `.factory/` as markdown files. Never put plan or review text in code comments.
- Only the paths in SCOPE (factory.conf) may change. Do not touch factory.sh, lib/, gates/, .claude/, data/ or this file.
