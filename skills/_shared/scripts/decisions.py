#!/usr/bin/env python3
"""Append a numbered, dated entry to docs/project/decisions.md, proving an owner ruling in the same call.

Usage:
  decisions.py add <project> --title "<title>" --body "<text>"
                   [--source-owner "<the owner's words>" [--session <id> | --session codex:<id>] | --proposed]
  decisions.py next-id <project>
Each <project> may also be the decisions.md file itself.

add writes the next entry, D-<nnn> (one more than the highest number in the file, so a number is never reused):
  ## D-<nnn> · <today> · <title>
  <body, as given: Decision:, Why:, Alternatives:, Affects:, Supersedes: lines and the like>
  Source: [owner <today>] "<the owner's words>"      with --source-owner
  Source: [proposed]                                 with --proposed
With --source-owner it first runs `rulings.py record <project> --id D-<nnn> --quote "<words>" [--session <id>]`,
and when the words cannot be proven to be a whole sentence (or the whole message) the owner typed, nothing is
written and the call fails. An owner source comes only through --source-owner: a title or body holding
"[owner" is refused, as is a body with its own Source line or a "## " line (it would start another entry). Every
line break Python knows (a carriage return, U+2028, U+0085, and the like) counts as one, so the checks see the
lines the file will hold. A missing decisions.md is started from the template's header. Prints the new ID on the
last line.
Two adds at once never take the same number: each holds an exclusive lock (fcntl) on .decisions.md.flock beside
decisions.md while it reads the next number, proves the ruling, and appends the entry; the file is appended
to, never rewritten.
next-id prints the ID the next entry would get.

Exit 0 on success, 1 when the entry cannot be written (the ruling is not proven, the body is refused), 2 on bad
usage.
"""
import datetime
import fcntl
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "templates/decisions.md"
HEAD = re.compile(r"^## D-(\d{3,})\b", re.M)
VALUE_OPTIONS = ("--title", "--body", "--source-owner", "--session")
LOCK_NAME = ".decisions.md.flock"  # not *.lock: regate_scope.py reads a *.lock file as a dependency lockfile


def path_of(arg):
    p = Path(arg)
    if p.name == "decisions.md" and not p.is_dir():
        return p
    return p / "docs/project/decisions.md"


def next_id(text):
    numbers = [int(n) for n in HEAD.findall(text or "")]
    return f"D-{(max(numbers) + 1 if numbers else 1):03d}"


def header():
    """The template's text above its example entry, else a bare title."""
    try:
        text = TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return "# Decisions\n"
    m = HEAD.search(text)
    return (text[:m.start()] if m else text).rstrip("\n") + "\n"


def parse(argv):
    """(options, error message or None) for add's arguments."""
    opts, i = {}, 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--proposed":
            opts[tok] = True
            i += 1
        elif tok in VALUE_OPTIONS and i + 1 < len(argv):
            opts[tok] = argv[i + 1]
            i += 2
        else:
            return opts, f"unexpected argument '{tok}'"
    if not (opts.get("--title") or "").strip() or not (opts.get("--body") or "").strip():
        return opts, "add needs --title and --body"
    for name in ("--title", "--body"):  # every break splitlines() knows becomes \n, so the checks see real lines
        opts[name] = "\n".join(opts[name].splitlines())
    if "\n" in opts["--title"]:
        return opts, "the title is one line"
    if "--source-owner" in opts and "--proposed" in opts:
        return opts, "an entry is either the owner's (--source-owner) or proposed (--proposed), not both"
    if "--session" in opts and "--source-owner" not in opts:
        return opts, "--session goes with --source-owner (it names where the owner typed the words)"
    return opts, None


def refused(opts):
    """Why the body or quote cannot be written as given, or None."""
    body, quote = opts["--body"], opts.get("--source-owner")
    if re.search(r"^## ", body, re.M):
        return "the body has a line starting with '## ', which would start another entry"
    for part, text in (("title", opts["--title"]), ("body", body)):
        if "[owner" in text:
            return (f"the {part} names an owner ruling; pass the owner's words with --source-owner so they are "
                    "proven, or write the entry --proposed and ask")
    if re.search(r"^Source:", body, re.M) and ("--source-owner" in opts or "--proposed" in opts):
        return "the body has its own Source line; give the source only through --source-owner or --proposed"
    if quote is not None and (not quote.strip() or '"' in quote):
        return ("the owner's words must be non-empty and hold no double quotes, so the entry quotes them exactly as "
                "rulings.py proves them")
    return None


def add(project_arg, argv):
    opts, problem = parse(argv)
    if problem:
        print(f"decisions: {problem}", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        return 2
    why = refused(opts)
    if why:
        print(f"FAIL   decisions   nothing written: {why}")
        return 1
    path = path_of(project_arg)
    project = path.parents[2] if path.parent.name == "project" and path.parent.parent.name == "docs" else path.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.parent / LOCK_NAME, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # held until the entry is appended; the kernel drops it if this dies
        try:
            return write_entry(path, project, opts)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def write_entry(path, project, opts):
    """Under the lock: read the file afresh, take the next number, prove the ruling, append the entry."""
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    did = next_id(text)
    today = datetime.date.today().isoformat()
    lines = [f"## {did} · {today} · {opts['--title'].strip()}"] + [l.rstrip() for l in opts["--body"].strip().splitlines()]
    if "--source-owner" in opts:
        quote = re.sub(r"\s+", " ", opts["--source-owner"]).strip()  # one line; rulings.py compares words alike
        cmd = [sys.executable, str(HERE / "rulings.py"), "record", str(project), "--id", did, "--quote", quote]
        if opts.get("--session"):
            cmd += ["--session", opts["--session"]]
        proof = subprocess.run(cmd, capture_output=True, text=True)
        shown = (proof.stdout + proof.stderr).strip()
        if shown:
            print(shown)
        if proof.returncode != 0:
            print(f"FAIL   decisions   {did} not written: the owner's words are not proven (rulings.py record "
                  f"exited {proof.returncode}). Quote a whole sentence the owner typed, or write it --proposed and ask.")
            return 1
        lines.append(f'Source: [owner {today}] "{quote}"')
    elif "--proposed" in opts:
        lines.append("Source: [proposed]")
    entry = "\n".join(lines) + "\n"
    if text is None:
        addition = header().rstrip("\n") + "\n\n" + entry
    else:  # one blank line between the file's last line and the entry, whatever the file ends with
        trailing = len(text) - len(text.rstrip("\n"))
        addition = ("\n" * max(0, 2 - trailing) if text.strip() else "") + entry
    with open(path, "a", encoding="utf-8") as f:
        f.write(addition)
    print(did)
    return 0


def main(argv):
    if len(argv) < 2 or argv[0] not in ("add", "next-id") or argv[1].startswith("-"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if argv[0] == "next-id":
        if len(argv) != 2:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        path = path_of(argv[1])
        print(next_id(path.read_text(encoding="utf-8") if path.is_file() else ""))
        return 0
    return add(argv[1], argv[2:])


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
