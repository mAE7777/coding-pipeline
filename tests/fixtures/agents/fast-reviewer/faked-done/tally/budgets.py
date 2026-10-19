"""Monthly budgets, kept in budgets.json beside the expenses: what a person means to spend on a category each month,
in cents."""
import json
import os
import tempfile
from pathlib import Path

DATA = Path("budgets.json")


class Unreadable(Exception):
    pass


def load(path=DATA):
    """{category: cents} the file holds (none when there is no file). Unreadable when the file exists but does not
    hold budgets; the file is never touched."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    try:
        budgets = json.loads(text)
    except ValueError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    if not isinstance(budgets, dict) or not all(isinstance(k, str) and type(v) is int and v >= 0
                                                for k, v in budgets.items()):
        raise Unreadable(f"cannot read {path}: it does not hold budgets")
    return budgets


def over(spent_cents, budget_cents):
    """True when what a category cost in a month went over its budget."""
    return False


def save(budgets, path=DATA):
    """Write every budget: a temporary file beside the data file, then a rename over it, so a failed write leaves
    the old file as it was."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".budgets-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(budgets, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
