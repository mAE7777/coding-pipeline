#!/usr/bin/env python3
"""Compare the vendored craft layer (skills/code-craft/) with pstack, the upstream it was copied from.

Usage: craft_sync.py [--upstream <pstack checkout>] [--craft <dir>] [--json] [--diff]
       craft_sync.py verify [--craft <dir>] [--json]

Compare (the default) reads the craft folder's UPSTREAM.json and, for every entry, the file at the same path in
a newer pstack checkout: the pstack folder of cursor/plugins, or the repository root that holds it.
--upstream defaults to $PSTACK_DIR. One line per entry:
  unchanged          upstream still matches the recorded sha256 and the local file is verbatim
  local edit         upstream still matches; the local file carries the recorded edit (local_edit)
  upstream changed   upstream differs from the recorded sha256; the line counts the unified diff
                     (+added -removed) from the recorded text to the new one
  missing upstream   the upstream path no longer exists
The recorded text is the local file when it is verbatim, else `git show <commit>:<path>` when the checkout
has that commit; failing both, the diff is taken against the local file and the line says so. --diff also
prints each unified diff. Exit 0 when nothing changed upstream, 1 when something did (changed or missing),
2 on bad usage (no checkout named, not a pstack checkout, no readable UPSTREAM.json).

verify checks the local side only: each entry whose local_edit is null is byte-identical to its recorded
upstream sha256, each entry with a local edit differs from it, every listed file exists, and every file in
the craft folder is listed (or named in "own"). Exit 0 when all hold, 1 otherwise, 2 on bad usage.

--craft defaults to skills/code-craft beside this script's skills folder. --json prints one JSON object.
--help prints this text and exits 0.
"""
import difflib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_CRAFT = Path(__file__).resolve().parents[2] / "code-craft"
SKIP_PARTS = {"__pycache__", ".DS_Store"}


class Usage(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_manifest(craft):
    path = craft / "UPSTREAM.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Usage(f"cannot read {path}: {e}")
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        raise Usage(f"{path} has no 'files' list")
    for i, e in enumerate(files):
        missing = [k for k in ("local", "upstream", "commit", "sha256", "local_edit") if not isinstance(e, dict)
                   or k not in e]
        if missing:
            raise Usage(f"{path} entry {i} lacks {', '.join(missing)}")
    return manifest


def pstack_root(path):
    p = Path(path).expanduser()
    for root in (p, p / "pstack"):
        if (root / "skills").is_dir() and (root / "LICENSE").is_file():
            return root
    raise Usage(f"{path} is not a pstack checkout (no skills/ and LICENSE there or in its pstack/ folder)")


def old_from_git(root, commit, upstream, want):
    try:
        r = subprocess.run(["git", "-C", str(root), "show", f"{commit}:./{upstream}"], capture_output=True)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 and sha256(r.stdout) == want else None


def text_lines(data):
    return data.decode("utf-8", errors="replace").splitlines()


def compare(craft, upstream_dir, want_diff):
    manifest = load_manifest(craft)
    root = pstack_root(upstream_dir)
    rows = []
    for e in manifest["files"]:
        row = {"local": e["local"], "upstream": e["upstream"], "local_edit": e["local_edit"]}
        new_path = root / e["upstream"]
        if not new_path.is_file():
            row["status"] = "missing upstream"
            rows.append(row)
            continue
        new = new_path.read_bytes()
        if sha256(new) == e["sha256"]:
            row["status"] = "unchanged" if e["local_edit"] is None else "local edit"
            rows.append(row)
            continue
        local_path = craft / e["local"]
        local = local_path.read_bytes() if local_path.is_file() else b""
        if e["local_edit"] is None and sha256(local) == e["sha256"]:
            old, against = local, "recorded"
        else:
            old = old_from_git(root, e["commit"], e["upstream"], e["sha256"])
            against = "recorded" if old is not None else "local"
            if old is None:
                old = local
        diff = list(difflib.unified_diff(text_lines(old), text_lines(new), f"{against}/{e['upstream']}",
                                         f"upstream/{e['upstream']}", lineterm=""))
        added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
        row.update(status="upstream changed", added=added, removed=removed, against=against)
        if want_diff:
            row["diff"] = diff
        rows.append(row)
    changed = sum(1 for r in rows if r["status"] in ("upstream changed", "missing upstream"))
    return {"upstream": str(root), "commit": manifest.get("upstream", {}).get("commit"), "entries": rows,
            "changed": changed}, (1 if changed else 0)


def listed_files(craft):
    for p in sorted(craft.rglob("*")):
        if p.is_file() and not any(part in SKIP_PARTS for part in p.relative_to(craft).parts):
            yield p.relative_to(craft).as_posix()


def verify(craft):
    manifest = load_manifest(craft)
    problems = []
    for e in manifest["files"]:
        path = craft / e["local"]
        if not path.is_file():
            problems.append(f"{e['local']}: listed but missing")
            continue
        same = sha256(path.read_bytes()) == e["sha256"]
        if e["local_edit"] is None and not same:
            problems.append(f"{e['local']}: differs from {e['upstream']} at {e['commit']} but local_edit is null")
        elif e["local_edit"] is not None and same:
            problems.append(f"{e['local']}: identical to {e['upstream']} but local_edit says it was changed")
    named = {e["local"] for e in manifest["files"]} | set(manifest.get("own", []))
    for rel in listed_files(craft):
        if rel not in named:
            problems.append(f"{rel}: not listed in UPSTREAM.json")
    return {"craft": str(craft), "entries": len(manifest["files"]), "problems": problems}, (1 if problems else 0)


def parse(argv):
    opts = {"mode": "compare", "craft": DEFAULT_CRAFT, "upstream": os.environ.get("PSTACK_DIR"), "json": False,
            "diff": False}
    args = list(argv)
    if args and args[0] == "verify":
        opts["mode"] = "verify"
        args = args[1:]
    compare_only = {"--upstream", "--diff"}
    while args:
        a = args.pop(0)
        if a in compare_only and opts["mode"] == "verify":
            raise Usage(f"{a} does not apply to verify")
        if a in ("--craft", "--upstream"):
            if not args:
                raise Usage(f"{a} needs a path")
            opts[a[2:]] = Path(args.pop(0))
        elif a in ("--json", "--diff"):
            opts[a[2:]] = True
        else:
            raise Usage(f"unknown argument: {a}")
    if not Path(opts["craft"]).is_dir():
        raise Usage(f"no craft folder at {opts['craft']}")
    if opts["mode"] == "compare" and not opts["upstream"]:
        raise Usage("name the newer pstack checkout with --upstream <dir> or PSTACK_DIR")
    return opts


def print_compare(result, want_diff):
    for r in result["entries"]:
        if r["status"] == "upstream changed":
            base = "" if r["against"] == "recorded" else ", against the local file"
            note = f"  (+{r['added']} -{r['removed']} lines{base})"
        elif r["status"] == "local edit":
            note = f"  ({r['local_edit']})"
        else:
            note = ""
        print(f"{r['status']:<17} {r['local']}  <- {r['upstream']}{note}")
        if want_diff and r.get("diff"):
            print("\n".join(r["diff"]))
    print(f"craft_sync: {result['changed']} upstream change(s) since {result['commit']} in {result['upstream']}")


def main(argv):
    try:
        opts = parse(argv)
        craft = Path(opts["craft"]).resolve()
        if opts["mode"] == "verify":
            result, code = verify(craft)
        else:
            result, code = compare(craft, opts["upstream"], opts["diff"])
    except Usage as e:
        print(f"craft_sync: {e}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2
    if opts["json"]:
        print(json.dumps(result, indent=2))
    elif opts["mode"] == "verify":
        for p in result["problems"]:
            print(f"FAIL  {p}")
        print(f"craft_sync verify: {'FAIL' if code else 'PASS'} ({result['entries']} entries, "
              f"{len(result['problems'])} problem(s))")
    else:
        print_compare(result, opts["diff"])
    return code


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or "-h" in sys.argv[1:3]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
