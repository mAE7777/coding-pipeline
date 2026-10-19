"""The command line: add, total, export, budget, and status."""
import argparse
import csv
import re
import sys

from tally import budgets, dates, money, status, store
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
    budget = sub.add_parser("budget", help="set what a category may cost each month")
    budget.add_argument("category")
    budget.add_argument("amount")
    month = sub.add_parser("status", help="show a month's spending against each budget")
    month.add_argument("month", metavar="YYYY-MM")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        ledger = store.load()
    except store.Unreadable as exc:
        return refuse(f"{exc}; the file was left untouched")
    limits = {}
    if args.cmd in ("budget", "status"):
        try:
            limits = budgets.load()
        except budgets.Unreadable as exc:
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
    elif args.cmd == "budget":
        try:
            cents = money.parse_amount(args.amount)
        except ValueError as exc:
            return refuse(str(exc))
        limits[args.category] = cents
        try:
            budgets.save(limits)
        except OSError as exc:
            return refuse(f"cannot save {budgets.DATA}: {exc}; nothing was recorded")
        print(f"budget for {args.category}: {money.format_amount(cents)} a month")
    elif args.cmd == "status":
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
            return refuse(f"not a month: {args.month} (use YYYY-MM)")
        lines = status.lines(ledger, limits, args.month)
        print("\n".join(lines) if lines else "no budgets yet")
    else:
        out = csv.writer(sys.stdout, lineterminator="\n")
        out.writerow(["day", "category", "amount"])
        for e in ledger.expenses():
            out.writerow([e.day, cell(e.category), money.format_amount(e.cents)])
    return 0
