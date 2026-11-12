import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from report.expenses import Expense, ReportError, parse_row, read_expenses, summary

ROW = {"date": "2026-10-03", "description": "Taxi", "amount": "12.50", "currency": "usd"}


def write_csv(text: str) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return Path(f.name)


class ParseRow(unittest.TestCase):
    def test_reads_a_row(self) -> None:
        self.assertEqual(parse_row(ROW, 2), Expense(date(2026, 10, 3), "Taxi", Decimal("12.50"), "USD"))

    def test_bad_date_names_the_line(self) -> None:
        with self.assertRaisesRegex(ReportError, "line 7"):
            parse_row({**ROW, "date": "03/10/2026"}, 7)

    def test_bad_amount(self) -> None:
        with self.assertRaises(ReportError):
            parse_row({**ROW, "amount": "twelve"}, 2)

    def test_bad_currency(self) -> None:
        with self.assertRaisesRegex(ReportError, "3-letter"):
            parse_row({**ROW, "currency": "dollars"}, 2)


class ReadAndSummarise(unittest.TestCase):
    def test_reads_a_file(self) -> None:
        path = write_csv("date,description,amount,currency\n2026-10-03,Taxi,12.50,USD\n2026-10-05,Lunch,9,EUR\n")
        self.assertEqual([e.currency for e in read_expenses(path)], ["USD", "EUR"])

    def test_error_line_counts_the_header(self) -> None:
        path = write_csv("date,description,amount,currency\n2026-10-03,Taxi,x,USD\n")
        with self.assertRaisesRegex(ReportError, "line 2"):
            read_expenses(path)

    def test_summary(self) -> None:
        expenses = [parse_row(ROW, 2), parse_row({**ROW, "date": "2026-09-30"}, 3)]
        self.assertEqual(summary(expenses), "2 expenses from 2026-09-30 to 2026-10-03")

    def test_summary_of_nothing(self) -> None:
        self.assertEqual(summary([]), "No expenses.")


def write_file(suffix: str, text: str) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return Path(f.name)


JSON = '[{"date":"2026-10-03","description":"Taxi","amount":12.5,"currency":"usd"},{"date":"2026-10-05","description":"Lunch","amount":"9","currency":"EUR"}]'
WANT = [Expense(date(2026, 10, 3), "Taxi", Decimal("12.5"), "USD"), Expense(date(2026, 10, 5), "Lunch", Decimal("9"), "EUR")]


class Formats(unittest.TestCase):
    def test_json(self) -> None:
        self.assertEqual(read_expenses(write_file(".json", JSON)), WANT)

    def test_extension_case_insensitive(self) -> None:
        self.assertEqual(read_expenses(write_file(".JSON", JSON)), WANT)

    def test_xml(self) -> None:
        xml = "<expenses>" + "".join(
            f"<expense><date>{e.day}</date><description>{e.description}</description>"
            f"<amount>{e.amount}</amount><currency>{e.currency}</currency></expense>" for e in WANT
        ) + "</expenses>"
        self.assertEqual(read_expenses(write_file(".xml", xml)), WANT)

    def test_xlsx(self) -> None:
        cells = ["date", "description", "amount", "currency", "2026-10-03", "Taxi", "12.5", "usd", "2026-10-05", "Lunch", "9", "EUR"]
        ss = "<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>" + "".join(f"<si><t>{c}</t></si>" for c in cells) + "</sst>"
        rows = "".join("<row>" + "".join(f"<c t='s'><v>{r * 4 + i}</v></c>" for i in range(4)) + "</row>" for r in range(3))
        sheet = f"<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>{rows}</sheetData></worksheet>"
        path = Path(tempfile.mkdtemp()) / "e.xlsx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/sharedStrings.xml", ss)
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        self.assertEqual(read_expenses(path), WANT)

    def test_unknown_extension(self) -> None:
        with self.assertRaises(ReportError):
            read_expenses(write_file(".txt", "x"))

    def test_malformed_json(self) -> None:
        with self.assertRaises(ReportError):
            read_expenses(write_file(".json", "[{"))

    def test_bad_json_row_names_line(self) -> None:
        bad = JSON.replace('"9"', '"x"')
        with self.assertRaisesRegex(ReportError, "line 3"):
            read_expenses(write_file(".json", bad))

    def test_cli_json(self) -> None:
        out = subprocess.run([sys.executable, "-m", "report", str(write_file(".json", JSON))], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("expenses from", out.stdout)


class Cli(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "report", *args], capture_output=True, text=True)

    def test_prints_the_summary(self) -> None:
        out = self.run_cli("data/sample.csv")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("expenses from", out.stdout)

    def test_bad_file_exits_1(self) -> None:
        self.assertEqual(self.run_cli("missing.csv").returncode, 1)


if __name__ == "__main__":
    unittest.main()
