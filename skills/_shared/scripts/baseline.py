#!/usr/bin/env python3
"""Record and diff a milestone's starting point.

Usage:
  baseline.py record <project> M<k>
  baseline.py diff <project> M<k> [--max-bytes 200000]

record writes .evidence/baseline-M<k>.txt (the fingerprint and per-file hashes, fingerprint.py --list
format) and .evidence/baseline/M<k>/ (a copy of every product file: an APFS clone where the disk supports
it, so it costs almost no space). It refuses to overwrite an existing baseline for the same milestone:
the start of a milestone happens once.
diff prints the files added, deleted, and modified since then, followed by unified diffs of the modified
and added text files up to --max-bytes (the rest are listed as not shown, never silently dropped).
Exit 0 on success, 1 when there is no baseline or it cannot be written, 2 on bad usage.
"""
import difflib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fingerprint import fingerprint  # noqa: E402


def paths(project, mid):
    return project / f".evidence/baseline-{mid}.txt", project / f".evidence/baseline/{mid}"


def record(project, mid):
    listing, snap = paths(project, mid)
    if listing.exists() or snap.exists():
        print(f"baseline: {mid} already has a baseline ({listing}); a milestone starts once", file=sys.stderr)
        return 1
    fp, rows = fingerprint(project, "product")
    snap.mkdir(parents=True)
    for rel, h in rows:
        if h == "deleted":
            continue
        src, dst = project / rel, snap / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
            continue
        r = subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True)
        if r.returncode != 0:
            shutil.copy2(src, dst)
    listing.write_text(fp + "\n" + "".join(f"{h[:16]}  {rel}\n" for rel, h in rows))
    print(f"{mid} baseline {fp} · {len(rows)} files · {listing}")
    return 0


def read_listing(listing):
    lines = listing.read_text().splitlines()
    rows = {}
    for line in lines[1:]:
        if "  " in line:
            h, rel = line.split("  ", 1)
            rows[rel] = h
    return lines[0] if lines else "", rows


def text_of(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def diff(project, mid, max_bytes=200000):
    listing, snap = paths(project, mid)
    if not listing.is_file():
        print(f"baseline: no baseline for {mid} (run: baseline.py record <project> {mid} when the milestone starts)",
              file=sys.stderr)
        return 1, None
    fp_old, old = read_listing(listing)
    fp_new, rows = fingerprint(project, "product")
    cur = {rel: h[:16] for rel, h in rows}
    added = sorted(set(cur) - set(old))
    deleted = sorted(set(old) - set(cur))
    modified = sorted(r for r in set(old) & set(cur) if old[r] != cur[r])
    out = [f"baseline {fp_old} -> now {fp_new}", ""]
    out += [f"added     {r}" for r in added] + [f"deleted   {r}" for r in deleted] + [f"modified  {r}" for r in modified]
    if not (added or deleted or modified):
        out.append("no changes")
    budget, skipped = max_bytes, []
    for rel in modified + added:
        new = text_of(project / rel)
        oldt = text_of(snap / rel) if rel in old else ""
        if new is None or oldt is None:
            skipped.append(f"{rel} (binary)")
            continue
        chunk = "".join(difflib.unified_diff(oldt.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
        if len(chunk) > budget:
            skipped.append(f"{rel} ({len(chunk)} bytes of diff)")
            continue
        budget -= len(chunk)
        out.append("")
        out.append(chunk.rstrip("\n"))
    if skipped:
        out += ["", "Diff not shown (over the size budget or binary), inspect in the copy:"] + [f"- {s}" for s in skipped]
    return 0, "\n".join(out)


def main(argv):
    if len(argv) < 3 or argv[0] not in ("record", "diff"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project, mid = Path(argv[1]).resolve(), argv[2]
    if argv[0] == "record":
        return record(project, mid)
    mb = int(argv[argv.index("--max-bytes") + 1]) if "--max-bytes" in argv else 200000
    code, text = diff(project, mid, mb)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
