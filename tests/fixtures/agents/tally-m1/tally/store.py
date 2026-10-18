"""The data file, expenses.json in the current folder: read whole, written whole through a rename."""
import dataclasses
import json
import os
import tempfile
from pathlib import Path

from tally.ledger import Expense, Ledger

DATA = Path("expenses.json")


class Unreadable(Exception):
    pass


def expense_of(row):
    if not (isinstance(row, dict) and isinstance(row.get("day"), str) and isinstance(row.get("category"), str)
            and type(row.get("cents")) is int and row["cents"] >= 0):
        raise ValueError(f"not an expense: {row!r}")
    return Expense(row["day"], row["category"], row["cents"])


def load(path=DATA):
    """The ledger the file holds (an empty one when there is no file). Unreadable when the file exists but cannot
    be read as a list of expenses; the file is never touched."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return Ledger()
    except (OSError, UnicodeDecodeError) as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    try:
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("not a list")
        return Ledger(expense_of(row) for row in rows)
    except ValueError as exc:
        raise Unreadable(f"cannot read {path}: it does not hold a list of expenses ({exc})") from exc


def save(ledger, path=DATA):
    """Write the whole ledger: a temporary file beside the data file, then a rename over it, so a failed write
    leaves the old file as it was."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".expenses-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([dataclasses.asdict(e) for e in ledger.expenses()], f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
