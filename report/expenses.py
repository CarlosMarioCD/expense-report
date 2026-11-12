"""Read expenses from a CSV, JSON, XML or XLSX file (date,description,amount,currency) and summarise them."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Expense:
    day: date
    description: str
    amount: Decimal
    currency: str


class ReportError(ValueError):
    """A row the report cannot use; the message names its line in the file."""


def parse_row(row: dict[str, str], line: int) -> Expense:
    try:
        day = date.fromisoformat(row["date"].strip())
        amount = Decimal(row["amount"].strip())
    except (KeyError, AttributeError, ValueError, InvalidOperation) as exc:
        raise ReportError(f"line {line}: cannot read date or amount ({exc})") from exc
    currency = (row.get("currency") or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ReportError(f"line {line}: currency must be a 3-letter code, got {currency!r}")
    return Expense(day, (row.get("description") or "").strip(), amount, currency)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _json_rows(path: Path) -> list[dict[str, str]]:
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ReportError(f"invalid JSON ({exc})") from exc
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ReportError("JSON must be an array of objects")
    return [{k: v if isinstance(v, str) else str(v) for k, v in i.items()} for i in items]


def _xml_rows(path: Path) -> list[dict[str, str]]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ReportError(f"invalid XML ({exc})") from exc
    return [{c.tag: c.text or "" for c in e} for e in root.iter("expense")]


def _xlsx_rows(path: Path) -> list[dict[str, str]]:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            sst = ET.fromstring(z.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in names else []
            strings = ["".join(t.text or "" for t in si.iter(ns + "t")) for si in sst]
            sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ReportError(f"invalid xlsx file ({exc})") from exc
    table = []
    for row in sheet.iter(ns + "row"):
        cells = []
        for c in row.iter(ns + "c"):
            v = c.find(ns + "v")
            t = "".join(x.text or "" for x in c.iter(ns + "t"))
            cells.append(strings[int(v.text)] if c.get("t") == "s" and v is not None else t if v is None else v.text or "")
        table.append(cells)
    return [dict(zip(table[0], r)) for r in table[1:]] if table else []


LOADERS = {".csv": _csv_rows, ".json": _json_rows, ".xml": _xml_rows, ".xlsx": _xlsx_rows}


def read_expenses(path: Path) -> list[Expense]:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ReportError(f"unsupported file type {path.suffix!r}")
    return [parse_row(row, n) for n, row in enumerate(loader(path), start=2)]


def summary(expenses: list[Expense]) -> str:
    if not expenses:
        return "No expenses."
    days = sorted(e.day for e in expenses)
    return f"{len(expenses)} expenses from {days[0].isoformat()} to {days[-1].isoformat()}"
