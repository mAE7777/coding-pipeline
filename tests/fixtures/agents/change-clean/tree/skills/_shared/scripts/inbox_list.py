#!/usr/bin/env python3
"""List the open items of an inbox file, one line per item: <id> · <who>: <their words>.

Usage: inbox_list.py <inbox.md>
An item line reads "- IN-<nnn> · <who>: <their words>"; other lines are ignored. The words are printed
exactly as written. Exit 0 after listing every item, 2 on bad usage.
"""
import sys
from pathlib import Path


def items(text):
    out = []
    for line in text.splitlines():
        if not line.startswith("- IN-"):
            continue
        ident, rest = line[2:].split(" · ", 1)
        # The proposer's name never contains ": "; their words may.
        who, words = rest.split(": ", 1)
        out.append((ident, who, words))
    return out


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    for ident, who, words in items(Path(argv[0]).read_text(encoding="utf-8")):
        print(f"{ident} · {who}: {words}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
