"""The command line: add, total, export, and archive."""
import argparse
import datetime
import re
import sys

from tally import archive, export, money, store


def refuse(message):
    print(f"error: {message}", file=sys.stderr)
    return 2


def day_of(text):
    """The day an expense was spent: YYYY-MM-DD as typed, or today."""
    if text is None:
        return datetime.date.today().isoformat()
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"not a day: {text} (use YYYY-MM-DD)") from None


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
    arc = sub.add_parser("archive", help="write one month's expenses to a CSV file")
    arc.add_argument("month", metavar="YYYY-MM")
    arc.add_argument("--to", default="archive", help="the folder for the file (default: archive)")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    items = store.load()
    if args.cmd == "add":
        try:
            item = {"day": day_of(args.on), "category": args.category, "cents": money.parse_amount(args.amount)}
        except ValueError as exc:
            return refuse(str(exc))
        try:
            store.save(items + [item])
        except OSError as exc:
            return refuse(f"cannot save {store.DATA}: {exc}; nothing was recorded")
        print(f"added {money.format_amount(item['cents'])} to {item['category']} on {item['day']}")
    elif args.cmd == "total":
        if not store.readable():
            return refuse(f"cannot read {store.DATA}: it does not hold JSON; the file was left untouched")
        cents = sum(i["cents"] for i in items if i["category"] == args.category)
        print(f"Total {args.category}: {money.format_amount(cents)}")
    elif args.cmd == "export":
        print("\n".join([export.HEADER, *export.csv_lines(items)]))
    else:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
            return refuse(f"not a month: {args.month} (use YYYY-MM)")
        try:
            path, count = archive.archive_month(items, args.month, args.to)
        except OSError as exc:
            return refuse(f"cannot write the archive: {exc}")
        print(f"archived {count} expense(s) to {path}")
    return 0
