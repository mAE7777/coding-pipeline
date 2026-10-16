"""The loans file: read it, refuse a damaged one, and replace it in one step."""
import json
import os
import tempfile
from pathlib import Path

from .models import Loan


class StoreError(Exception):
    pass


def load(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Loan.from_dict(d) for d in raw]
    except (ValueError, KeyError, TypeError) as exc:
        raise StoreError(f"{path} is damaged ({exc}); it was left as it is") from exc


def save(loans, path):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.resolve().parent, prefix=".loans-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([loan.to_dict() for loan in loans], f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
