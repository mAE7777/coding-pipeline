"""split: record shared expenses."""
import argparse
import json
import sys
from pathlib import Path

DATA = Path("shared.json")


def load():
    return json.loads(DATA.read_text()) if DATA.exists() else []


def save(items):
    DATA.write_text(json.dumps(items))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="split")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="record who paid what")
    add.add_argument("payer")
    add.add_argument("amount", type=float)
    add.add_argument("--category", default="general")
    sub.add_parser("totals", help="show totals per category")
    sub.add_parser("settle", help="say who owes whom to settle up")
    rm = sub.add_parser("delete", help="remove an expense for good (it cannot be restored)")
    rm.add_argument("index", type=int)
    args = parser.parse_args(argv)
    items = load()
    if args.cmd == "add":
        items.append({"payer": args.payer, "amount": args.amount, "category": args.category})
        save(items)
        print(f"recorded {args.amount:.2f} paid by {args.payer}")
    elif args.cmd == "totals":
        cats = {}
        for i in items:
            cats[i["category"]] = cats.get(i["category"], 0) + i["amount"]
        for c, v in sorted(cats.items()):
            print(f"{c}: {v:.2f}")
    elif args.cmd == "settle":
        paid = {}
        for i in items:
            paid[i["payer"]] = paid.get(i["payer"], 0) + i["amount"]
        if len(paid) < 2:
            print("nothing to settle")
        else:
            (a, pa), (b, pb) = sorted(paid.items(), key=lambda kv: -kv[1])[:2]
            print(f"{b} owes {a} {(pa - pb) / 2:.2f}")
    elif args.cmd == "delete":
        items.pop(args.index)
        save(items)
        print("deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
