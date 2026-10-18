"""The command line: add, total, export, and report."""
import argparse
import csv
import sys

from tally import dates, money, report, store
from tally.ledger import Expense

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def refuse(message):
    print(f"error: {message}", file=sys.stderr)
    return 2


def cell(text):
    """Text as a spreadsheet cell: a leading formula character is escaped with a quote."""
    return "'" + text if text.startswith(FORMULA_START) else text


def parser():
    p = argparse.ArgumentParser(prog="tally", description="Record expenses and see what each category costs.")
    sub = p.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="record an expense")
    add.add_argument("category")
    add.add_argument("amount")
    add.add_argument("--on", metavar="YYYY-MM-DD", help="the day of the expense (default: today)")
    total = sub.add_parser("total", help="show what one category cost")
    total.add_argument("category")
    sub.add_parser("export", help="print every expense as CSV")
    sub.add_parser("report", help="show what each category cost in each month")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        ledger = store.load()
    except store.Unreadable as exc:
        return refuse(f"{exc}; the file was left untouched")
    if args.cmd == "add":
        try:
            expense = Expense(dates.parse_day(args.on) if args.on else dates.today(), args.category,
                              money.parse_amount(args.amount))
        except ValueError as exc:
            return refuse(str(exc))
        ledger.add(expense)
        try:
            store.save(ledger)
        except OSError as exc:
            return refuse(f"cannot save {store.DATA}: {exc}; nothing was recorded")
        print(f"added {money.format_amount(expense.cents)} to {expense.category} on {expense.day}")
    elif args.cmd == "total":
        print(f"Total {args.category}: {money.format_amount(ledger.total(args.category))}")
    elif args.cmd == "report":
        lines = report.monthly(ledger.expenses())
        print("\n".join(lines) if lines else "no expenses yet")
    else:
        out = csv.writer(sys.stdout, lineterminator="\n")
        out.writerow(["day", "category", "amount"])
        for e in ledger.expenses():
            out.writerow([e.day, cell(e.category), money.format_amount(e.cents)])
    return 0
