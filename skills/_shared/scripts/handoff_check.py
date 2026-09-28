#!/usr/bin/env python3
"""Check that a handoff packet carries everything it must, so nothing is lost between sessions.

Usage: handoff_check.py <packet.md> [--project <dir>]

FAILs when: a required section is missing, empty, or says TBD / holds a template placeholder (angle
brackets around words with a space, like the templates use; a generic such as Map<string, List>, with a
name right before the bracket, is not one); a
read-list file is missing or its sha256 differs; the Candidate fingerprint differs from the tree; an
active constraint ID from docs/project/brief.md, a must-not-lose ID from docs/project/intent.md (re-freezes
applied), an open item from docs/project/state.md, a parked item from milestones.md, or an open or logged
gate finding from docs/project/reviews/*.findings.json is absent from the packet; an evidence path under
Done does not exist. Exit 0 = no FAIL, 1 = FAIL, 2 = bad usage.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fingerprint import fingerprint  # noqa: E402
from intent_lock import effective  # noqa: E402

REQUIRED = ["Authority", "Read list", "Candidate", "Done", "Open", "In flight", "Blockers",
            "Failures", "Carried forward", "Constraint IDs", "Must-not-lose IDs", "Next step", "Hand back"]
# An unfilled template: angle-bracket placeholders anywhere, or a line that is nothing but TBD / TODO. Real content
# that mentions a TODO ("remove the TODO in parser.py") is not a placeholder.
PLACEHOLDER = re.compile(r"(?<![\w.])<[a-z][^<>\n]*\s[^<>\n]*>|^\s*(?:[-*]\s*(?:\[[ x]\]\s*)?)?(?:TBD|TODO)\.?\s*$",
                         re.I | re.M)

results = []


def report(status, check, detail):
    results.append((status, check, detail))


def sections(text):
    out, name = {}, None
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            name = m.group(1).strip()
            out[name] = []
            continue
        if name is not None:
            out[name].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def active_constraints(brief_text):
    ids = []
    in_table = False
    for line in brief_text.splitlines():
        if line.startswith("## "):
            in_table = line.strip().lower().startswith("## constraints")
            continue
        if not in_table or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or not re.fullmatch(r"C-\d+", cells[0]):
            continue
        status = cells[-1].lower() if len(cells) > 1 else "active"
        if "supersed" in status or "retired" in status or "dropped" in status:
            continue
        ids.append(cells[0])
    return ids


def must_not_lose(intent_text):
    return list(effective(intent_text)["must_not_lose"])


def open_items(state_text):
    sec = sections(strip_comments(state_text)).get("Open", "")
    return [re.sub(r"\s+", " ", m.strip()).lower()
            for m in re.findall(r"^- \[ \]\s*(.+)$", sec, flags=re.M)]


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    packet = Path(argv[0])
    project = Path(".")
    if "--project" in argv:
        i = argv.index("--project")
        if i + 1 >= len(argv):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        project = Path(argv[i + 1])
    if not packet.is_file():
        print(f"handoff_check: no such packet: {packet}", file=sys.stderr)
        return 2
    text = strip_comments(packet.read_text(encoding="utf-8"))
    secs = sections(text)

    for name in REQUIRED:
        body = secs.get(name)
        if body is None:
            report("FAIL", "section", f"'## {name}' is missing")
        elif not body:
            report("FAIL", "section", f"'## {name}' is empty (write 'none' if there is nothing)")
        elif PLACEHOLDER.search(body):
            report("FAIL", "section", f"'## {name}' still holds a placeholder: {PLACEHOLDER.search(body).group(0)}")

    for m in re.finditer(r"^- (\S+) · sha256 ([0-9a-f]{64})\s*$", secs.get("Read list", ""), flags=re.M):
        rel, want = m.group(1), m.group(2)
        path = project / rel
        if not path.is_file():
            report("FAIL", "read-list", f"{rel} does not exist")
        elif sha256(path) != want:
            report("FAIL", "read-list", f"{rel} changed since the packet was written")
        else:
            report("PASS", "read-list", f"{rel} matches")
    if not re.search(r"sha256 [0-9a-f]{64}", secs.get("Read list", "")):
        report("FAIL", "read-list", "no file with a sha256 listed")

    cand = secs.get("Candidate", "").strip().split()
    if cand:
        scope = cand[0].split(":")[0] if ":" in cand[0] else "product"
        now, _ = fingerprint(project, scope if scope in ("product", "all") else "product")
        if cand[0] != now:
            report("FAIL", "candidate", f"packet says {cand[0]}, tree is {now}")
        else:
            report("PASS", "candidate", f"fingerprint {now} matches the tree")

    brief = project / "docs/project/brief.md"
    if brief.is_file():
        for cid in active_constraints(brief.read_text(encoding="utf-8")):
            if not re.search(rf"\b{re.escape(cid)}\b", secs.get("Constraint IDs", "")):
                report("FAIL", "constraints", f"active constraint {cid} is not carried")
    else:
        report("WARN", "constraints", "no docs/project/brief.md to check constraint IDs against")

    intent = project / "docs/project/intent.md"
    if intent.is_file():
        for lid in must_not_lose(intent.read_text(encoding="utf-8")):
            if not re.search(rf"\b{re.escape(lid)}\b", secs.get("Must-not-lose IDs", "")):
                report("FAIL", "must-not-lose", f"{lid} is not carried")
    else:
        report("WARN", "must-not-lose", "no docs/project/intent.md to check against")

    state = project / "docs/project/state.md"
    if state.is_file():
        carried = " ".join(re.sub(r"\s+", " ", l).lower() for l in secs.get("Open", "").splitlines())
        for item in open_items(state.read_text(encoding="utf-8")):
            if item not in carried:
                report("FAIL", "open-items", f"open item not carried: {item[:70]}")
    else:
        report("WARN", "open-items", "no docs/project/state.md to check against")

    carried_fw = secs.get("Carried forward", "")
    ms = project / "docs/project/milestones.md"
    if ms.is_file():
        for line in ms.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item.startswith("- ") and "re-enable:" in item:
                key = item[2:].split("·")[0].strip()
                if key and key not in carried_fw:
                    report("FAIL", "carried", f"parked item not carried forward: {key[:60]}")
    reviews = project / "docs/project/reviews"
    for ledger in sorted(reviews.glob("*.findings.json")) if reviews.is_dir() else []:
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except ValueError:
            report("FAIL", "carried", f"{ledger.name} is not valid JSON")
            continue
        for fid, row in data.items():
            if row.get("status") in ("open", "logged") and fid not in carried_fw:
                report("FAIL", "carried", f"gate finding {fid} ({row.get('status')}) not carried forward")

    for rel in re.findall(r"evidence:\s*(\S+)", secs.get("Done", "")):
        rel = rel.lstrip("`'\"([").rstrip("`'\")].,;:")
        if not rel or not (project / rel).exists():
            report("FAIL", "evidence", f"Done cites {rel}, which does not exist")

    fails = sum(1 for r in results if r[0] == "FAIL")
    for status, check, detail in results:
        print(f"{status:<5}  {check:<13}  {detail}")
    print(f"handoff_check: {'FAIL' if fails else 'PASS'} ({fails} failing check(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
