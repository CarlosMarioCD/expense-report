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


def write_file(suffix: str, text: str = "", files: dict[str, str] | None = None) -> Path:
    f = tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False)
    f.close()
    if files is None:
        Path(f.name).write_text(text, encoding="utf-8")
    else:
        with zipfile.ZipFile(f.name, "w") as z:
            for name, body in files.items():
                z.writestr(name, body)
    return Path(f.name)


def xlsx(amount: str) -> Path:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'

    def s(ref: str, v: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'

    head = "".join(s(f"{c}1", h) for c, h in zip("ABCD", ["date", "description", "amount", "currency"]))
    r2 = s("A2", "2026-10-03") + '<c r="B2" t="s"><v>0</v></c>' + f'<c r="C2"><v>{amount}</v></c>' + s("D2", "usd")
    sheet = f'<worksheet {ns}><sheetData><row r="1">{head}</row><row r="2">{r2}</row></sheetData></worksheet>'
    strings = f'<sst {ns}><si><t>Taxi</t></si></sst>'
    return write_file(".xlsx", files={"xl/worksheets/sheet1.xml": sheet, "xl/sharedStrings.xml": strings})


JSON = '[{"date":"2026-10-03","description":"Taxi","amount":12.5,"currency":"usd"},{"date":"2026-10-05","description":"Lunch","amount":"9","currency":"EUR"}]'
XML = (
    "<expenses><expense><date>2026-10-03</date><description>Taxi</description><amount>12.5</amount><currency>usd</currency></expense>"
    "<expense><date>2026-10-05</date><description>Lunch</description><amount>9</amount><currency>EUR</currency></expense></expenses>"
)
EXPECTED = [
    Expense(date(2026, 10, 3), "Taxi", Decimal("12.5"), "USD"),
    Expense(date(2026, 10, 5), "Lunch", Decimal("9"), "EUR"),
]


class Formats(unittest.TestCase):
    def test_json(self) -> None:
        self.assertEqual(read_expenses(write_file(".json", JSON)), EXPECTED)

    def test_xml(self) -> None:
        self.assertEqual(read_expenses(write_file(".xml", XML)), EXPECTED)

    def test_xlsx(self) -> None:
        self.assertEqual(read_expenses(xlsx("12.5")), [EXPECTED[0]])

    def test_extension_is_case_insensitive(self) -> None:
        self.assertEqual(read_expenses(write_file(".JSON", JSON)), EXPECTED)

    def test_json_error_names_the_line(self) -> None:
        with self.assertRaisesRegex(ReportError, "line 3"):
            read_expenses(write_file(".json", JSON.replace('"9"', '"x"')))

    def test_xlsx_error_names_the_row(self) -> None:
        with self.assertRaisesRegex(ReportError, "line 2"):
            read_expenses(xlsx("abc"))

    def test_unsupported_extension(self) -> None:
        with self.assertRaises(ReportError):
            read_expenses(write_file(".txt", "x"))

    def test_malformed_json(self) -> None:
        with self.assertRaises(ReportError):
            read_expenses(write_file(".json", "[{"))


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
