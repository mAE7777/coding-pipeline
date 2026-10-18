"""The data file, expenses.json in the current folder: a list of {day, category, cents}, written whole."""
import json
import os
import tempfile
from pathlib import Path

DATA = Path("expenses.json")


class Unreadable(Exception):
    pass


def is_expense(item):
    return (isinstance(item, dict) and isinstance(item.get("day"), str) and isinstance(item.get("category"), str)
            and type(item.get("cents")) is int and item["cents"] >= 0)


def load(path=DATA):
    """The expenses the file holds; none when there is no file. Unreadable when the file exists but is not a list
    of expenses; the file is never touched."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    try:
        items = json.loads(text)
    except ValueError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    if not isinstance(items, list) or not all(is_expense(i) for i in items):
        raise Unreadable(f"cannot read {path}: it does not hold a list of expenses")
    return items


def save(items, path=DATA):
    """Write every expense through a temporary file and a rename, so a failed write leaves the old file."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".expenses-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
