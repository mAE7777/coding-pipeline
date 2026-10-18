"""The command line: add, total, export, and import."""
import argparse
import csv
import sys

from tally import categorize, dates, dedupe, importer, money, store
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
    imp = sub.add_parser("import", help="record the spending lines of a bank statement (CSV)")
    imp.add_argument("statement", help="the CSV file the bank exported")
    imp.add_argument("--dry-run", action="store_true", help="show what would be recorded and record nothing")
    return p


def import_statement(ledger, path, dry_run):
    """Record every spending line of the statement not recorded yet, categorized by rules.txt, in one save."""
    try:
        statement = importer.read_statement(path)
        rules = categorize.load_rules()
    except (importer.BadStatement, categorize.BadRules) as exc:
        return refuse(f"{exc}; nothing was recorded")
    found = dedupe.split(statement.spending, ledger.expenses())
    for t in found.new:
        expense = Expense(t.day, categorize.category_of(t.payee, rules), t.cents, t.payee)
        if dry_run:
            print(f"would add {money.format_amount(expense.cents)} to {expense.category} on {expense.day} "
                  f"({expense.payee})")
        ledger.add(expense)
    if found.new and not dry_run:
        try:
            store.save(ledger)
        except OSError as exc:
            return refuse(f"cannot save {store.DATA}: {exc}; nothing was recorded")
    print(f"{'would import' if dry_run else 'imported'} {len(found.new)} expense(s) from the {statement.bank} "
          f"statement ({len(found.already)} already recorded, {statement.income_lines} income line(s) skipped)")
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        ledger = store.load()
    except store.Unreadable as exc:
        return refuse(f"{exc}; the file was left untouched")
    if args.cmd == "import":
        return import_statement(ledger, args.statement, args.dry_run)
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
    else:
        out = csv.writer(sys.stdout, lineterminator="\n")
        out.writerow(["day", "category", "amount"])
        for e in ledger.expenses():
            out.writerow([e.day, cell(e.category), money.format_amount(e.cents)])
    return 0
