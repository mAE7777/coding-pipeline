"""tally: record expenses and show the total for a category."""
import argparse
import csv
import fcntl
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path

DATA = Path("expenses.json")
LOCK = Path(".tally.lock")
LARGEST = 1_000_000_000
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class Unreadable(Exception):
    pass


def valid_amount(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= LARGEST)


def amount(text):
    try:
        value = round(float(text), 2) + 0.0
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an amount: {text}")
    if not valid_amount(value):
        raise argparse.ArgumentTypeError(f"not an amount: {text} (use 0 to {LARGEST:,})")
    return value


def load(path=DATA):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    if not isinstance(items, list) or not all(
            isinstance(i, dict) and isinstance(i.get("category"), str) and valid_amount(i.get("amount"))
            for i in items):
        raise Unreadable(f"cannot read {path}: it does not hold a list of expenses")
    return items


def save(items, path=DATA):
    target = Path(os.path.realpath(path))
    try:
        mode = os.stat(target).st_mode & 0o777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".expenses-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def total(items, category):
    return round(sum(i["amount"] for i in items if i["category"] == category), 2)


def cell(text):
    return "'" + text if text.startswith(FORMULA_START) else text


def export_csv(items):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["category", "amount"])
    for i in items:
        writer.writerow([cell(i["category"]), f"{i['amount']:.2f}"])
    return out.getvalue().rstrip("\n")


def refuse(message):
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tally")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="record an expense")
    add.add_argument("category")
    add.add_argument("amount", type=amount)
    tot = sub.add_parser("total", help="show the total for one category")
    tot.add_argument("category")
    sub.add_parser("export", help="print every expense as CSV")
    args = parser.parse_args(argv)
    if args.cmd != "add":
        # Reads need no lock: a save replaces the file in one step, so a reader sees the old or the new file.
        try:
            items = load()
        except Unreadable as exc:
            return refuse(f"{exc}; the file was left untouched")
        print(f"Total {args.category}: {total(items, args.category):.2f}" if args.cmd == "total" else export_csv(items))
        return 0
    try:
        lock = open(LOCK, "a")
    except OSError as exc:
        return refuse(f"cannot lock {LOCK}: {exc}; nothing was recorded")
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            items = load()
        except Unreadable as exc:
            return refuse(f"{exc}; the file was left untouched")
        items.append({"category": args.category, "amount": args.amount})
        try:
            save(items)
        except OSError as exc:
            return refuse(f"cannot save {DATA}: {exc}; the file was left untouched")
    print(f"added {args.amount:.2f} to {args.category}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
