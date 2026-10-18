"""The data file, expenses.json in the current folder: a list of {day, category, cents}, written whole."""
import json
import os
import tempfile
from pathlib import Path

DATA = Path("expenses.json")


def load(path=DATA):
    """The expenses the file holds; none when there is no file."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except ValueError:
        return []


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
