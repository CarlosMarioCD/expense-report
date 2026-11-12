"""Read expenses from a CSV file (date,description,amount,currency) and summarise them."""

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


def _csv_rows(path: Path) -> list[tuple[int, dict]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(enumerate(csv.DictReader(f), start=2))


def _json_rows(path: Path) -> list[tuple[int, dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ReportError(f"{path.name}: expected a JSON array of objects")
    return [(n, {k: str(v) for k, v in r.items()}) for n, r in enumerate(data, start=2)]


def _xml_rows(path: Path) -> list[tuple[int, dict]]:
    root = ET.parse(path).getroot()
    return [(n, {c.tag: (c.text or "") for c in e}) for n, e in enumerate(root.iter("expense"), start=2)]


def _xlsx_rows(path: Path) -> list[tuple[int, dict]]:
    with zipfile.ZipFile(path) as z:
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.findall(".//{*}t")) for si in sst.findall("{*}si")]
    rows = []
    for row in sheet.findall(".//{*}row"):
        cells = {}
        for c in row.findall("{*}c"):
            col = "".join(ch for ch in c.get("r", "") if ch.isalpha())
            v = c.find("{*}v")
            if c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.findall(".//{*}t"))
            else:
                text = (v.text or "") if v is not None else ""
                text = shared[int(text)] if c.get("t") == "s" else text
            cells[col] = text
        rows.append((int(row.get("r", len(rows) + 1)), cells))
    names = rows[0][1] if rows else {}
    return [(n, {names[col]: v for col, v in cells.items() if col in names}) for n, cells in rows[1:]]


_READERS = {".csv": _csv_rows, ".json": _json_rows, ".xml": _xml_rows, ".xlsx": _xlsx_rows}


def read_expenses(path: Path) -> list[Expense]:
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        raise ReportError(f"{path.name}: unsupported file type, use .csv, .json, .xlsx or .xml")
    try:
        rows = reader(path)
    except (ValueError, ET.ParseError, zipfile.BadZipFile, KeyError) as exc:
        if isinstance(exc, ReportError):
            raise
        raise ReportError(f"{path.name}: cannot read file ({exc})") from exc
    return [parse_row(row, n) for n, row in rows]


def summary(expenses: list[Expense]) -> str:
    if not expenses:
        return "No expenses."
    days = sorted(e.day for e in expenses)
    return f"{len(expenses)} expenses from {days[0].isoformat()} to {days[-1].isoformat()}"
