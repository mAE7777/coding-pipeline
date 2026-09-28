"""tally: record expenses and show the total for a category."""
import argparse
import json
import sys
from pathlib import Path

from sample_data import SAMPLE

DATA = Path("expenses.json")


def load(path=DATA):
    if not path.exists():
        return list(SAMPLE)
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


def save(items, path=DATA):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items))
    tmp.replace(path)


def total(items, category):
    return round(sum(i["amount"] for i in items), 2)


def export_csv(items):
    lines = ["category,amount"] + [f"{i['category']},{i['amount']:.2f}" for i in items]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tally")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="record an expense")
    add.add_argument("category")
    add.add_argument("amount", type=float)
    tot = sub.add_parser("total", help="show the total for one category")
    tot.add_argument("category")
    args = parser.parse_args(argv)
    items = load()
    if args.cmd == "add":
        items.append({"category": args.category, "amount": args.amount})
        save(items)
        print(f"added {args.amount:.2f} to {args.category}")
    elif args.cmd == "total":
        print(f"Total {args.category}: {total(items, args.category):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
