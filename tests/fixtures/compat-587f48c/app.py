"""A short to-do list in a terminal: `python3 app.py add <item>` adds one, `python3 app.py` shows the list."""
import os
import sys
from pathlib import Path


def store():
    return Path(os.environ.get("LIST_FILE") or Path(__file__).resolve().parent / "list.txt")


def load():
    return store().read_text(encoding="utf-8").splitlines() if store().is_file() else []


def show(items):
    if not items:
        return "(empty)"
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))


def main(argv):
    items = load()
    if argv[:1] == ["add"] and len(argv) > 1:
        items.append(" ".join(argv[1:]))
        store().write_text("\n".join(items) + "\n", encoding="utf-8")
    print(show(items))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
