"""The shelf command line: lend, return, list, overdue, export."""
import argparse
import datetime
import sys

from . import config, export, overdue, store
from .models import BadIsbn, Book, Loan, normalize_isbn


def cmd_lend(args, loans, today):
    days = args.days or config.loan_days()
    isbn = normalize_isbn(args.isbn) if args.isbn else ""
    loan = Loan(Book(args.title, isbn), args.borrower, today, today + datetime.timedelta(days=days))
    loans.append(loan)
    print(f"lent {args.title} to {args.borrower}, due {loan.due_on}")


def cmd_return(args, loans, today):
    out = [loan for loan in loans if loan.book.title == args.title and loan.returned_on is None]
    if not out:
        raise SystemExit(f"shelf: {args.title} is not out on loan")
    out[0].returned_on = today
    print(f"{args.title} is back from {out[0].borrower}")


def cmd_list(args, loans, today):
    for loan in loans:
        if loan.returned_on is None:
            flag = " OVERDUE" if loan.is_overdue(today) else ""
            print(f"{loan.book.title} -> {loan.borrower}, due {loan.due_on}{flag}")


def cmd_overdue(args, loans, today):
    for loan in overdue.overdue_loans(loans, today):
        print(overdue.reminder_text(loan, today))


def cmd_export(args, loans, today):
    export.write_csv(loans, args.out)
    print(f"wrote {len(loans)} loans to {args.out}")


HANDLERS = {"lend": cmd_lend, "return": cmd_return, "list": cmd_list, "overdue": cmd_overdue,
            "export": cmd_export}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="shelf")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lend = sub.add_parser("lend", help="record a book you lent")
    lend.add_argument("title")
    lend.add_argument("borrower")
    lend.add_argument("--isbn")
    lend.add_argument("--days", type=int, help="how long the loan lasts (default: two weeks)")
    back = sub.add_parser("return", help="a book came back")
    back.add_argument("title")
    sub.add_parser("list", help="books still out")
    sub.add_parser("overdue", help="a reminder for each overdue book")
    exp = sub.add_parser("export", help="every loan as CSV")
    exp.add_argument("out")
    args = parser.parse_args(argv)
    path = config.data_path()
    try:
        loans = store.load(path)
    except store.StoreError as exc:
        print(f"shelf: {exc}", file=sys.stderr)
        return 2
    try:
        HANDLERS[args.cmd](args, loans, datetime.date.today())
    except BadIsbn as exc:
        print(f"shelf: {exc}", file=sys.stderr)
        return 2
    if args.cmd in ("lend", "return"):
        store.save(loans, path)
    return 0
