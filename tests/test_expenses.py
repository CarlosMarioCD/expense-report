import subprocess
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from report.expenses import (Expense, ReportError, format_monthly, monthly_totals, parse_row,
                             read_expenses, summary)

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


class Monthly(unittest.TestCase):
    def exp(self, day: str, amount: str, cur: str) -> Expense:
        return Expense(date.fromisoformat(day), "x", Decimal(amount), cur)

    def test_sums_per_month_and_currency(self) -> None:
        got = monthly_totals([self.exp("2026-09-01", "12.50", "USD"), self.exp("2026-09-02", "0.10", "USD"),
                              self.exp("2026-09-03", "9.00", "EUR")])
        self.assertEqual(got, {"2026-09": {"EUR": Decimal("9.00"), "USD": Decimal("12.60")}})

    def test_months_are_chronological(self) -> None:
        got = monthly_totals([self.exp("2026-01-01", "1", "USD"), self.exp("2025-12-01", "1", "USD")])
        self.assertEqual(list(got), ["2025-12", "2026-01"])

    def test_format(self) -> None:
        text = format_monthly([self.exp("2026-10-01", "3.00", "USD"), self.exp("2026-09-01", "9.00", "EUR"),
                               self.exp("2026-09-02", "12.50", "USD")])
        self.assertEqual(text, "2026-09\n  EUR 9.00\n  USD 12.50\n2026-10\n  USD 3.00")

    def test_format_empty(self) -> None:
        self.assertEqual(format_monthly([]), "No expenses.")


class Cli(unittest.TestCase):
    def test_by_month_either_position(self) -> None:
        for args in (("data/sample.csv", "--by-month"), ("--by-month", "data/sample.csv")):
            out = self.run_cli(*args)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertRegex(out.stdout, r"(?m)^\d{4}-\d{2}$")

    def test_unknown_flag_exits_2(self) -> None:
        self.assertEqual(self.run_cli("data/sample.csv", "--nope").returncode, 2)

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
