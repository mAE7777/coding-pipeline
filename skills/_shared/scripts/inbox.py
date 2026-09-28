#!/usr/bin/env python3
"""The project's inbox: suggestions, proposed changes, and new ideas waiting to be weighed.

Usage:
  inbox.py add <project> --from "<who>" --kind <kind> (--text "<their words>" | --source "SRC-<n> T<a>-T<b>")
                         [--via "<channel>"] [--title "<short title>"]
  inbox.py list <project> [--json]
  inbox.py resolve <project> IN-<nnn> --decision D-<nnn>
  inbox.py check <project>

docs/project/inbox.md holds the open items, each "## IN-<nnn> · <date> · <title>" with From, Text (the
proposer's words verbatim, or Source citing captured turns), and Status (open, or "asked: <question>").
Kinds: opinion, change, idea, feedback, bug, question. "Next: IN-<nnn>" in the file is the next number, so
every number ever given out can be accounted for.

An item leaves the inbox only through `resolve`, which requires a decision entry in decisions.md that:
  Resolves: IN-<nnn> (...)            names the item
  Item: "<the item's words>"          quotes it (the text, or its Source line)
  Verdict: <verdict> · ...            ADOPT, ADOPT-PART, RESHAPE, PLACE M<k>, or REJECT
  Routed: <where each part went>      files and anchors, or "none" for a rejection
and is an owner ruling proven by rulings.py unless the builder may decide it alone: only a whole ADOPT that
stays inside the current contract (Routed names neither intent.md nor milestones.md). Declining input, in whole
or in part, reshaping it, and changing the intent or a milestone contract are the owner's calls; one owner
message may rule on a batch of items. `check` proves that every number below Next is open in the inbox or resolved by
such an entry, that nothing resolved is still listed, and that the owner rulings hold. It is part of the
gate's deterministic layer.

Prints PASS / FAIL / WARN / SKIP lines (add prints the new ID). Exit 0 when nothing FAILs, 1 otherwise, 2 on
bad usage.
"""
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

KINDS = ("opinion", "change", "idea", "feedback", "bug", "question")
VERDICT = re.compile(r"^Verdict:\s*(ADOPT-PART|ADOPT|RESHAPE|PLACE\s+M\d+|REJECT)\b", re.M)
ITEM = re.compile(r"^## (IN-\d{3,}) · .*?(?=^## IN-\d{3,} · |\Z)", re.M | re.S)
SECTION = re.compile(r"^## (D-\d{3,})\b.*?(?=^## D-\d{3,}\b|\Z)", re.M | re.S)
HEADER = """# Inbox

<!--
Suggestions, proposed changes, and new ideas waiting to be weighed: other people's opinions, user feedback,
review notes, and ideas the owner floated without deciding. Nothing here is a decision. Once an item is
decided, it leaves this file, and its entry in decisions.md quotes it and records where it went. Items are
numbered in order; a number is never reused, and an item is never deleted by hand.
-->

Next: IN-001
"""


def path(project):
    return Path(project) / "docs/project/inbox.md"


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def items(text):
    return {m.group(1): m.group(0) for m in ITEM.finditer(text)}


def next_number(text):
    m = re.search(r"^Next:\s*IN-(\d+)", text, re.M)
    return int(m.group(1)) if m else None


def item_words(block):
    """The item's own words: the quoted Text lines, else its Source line."""
    quoted = [l[1:].strip() if l.startswith(">") else "" for l in block.splitlines() if l.startswith(">")]
    if any(quoted):
        return norm(" ".join(quoted))
    m = re.search(r"^Source:\s*(.+)$", block, re.M)
    return norm(m.group(1)) if m else ""


def entries(project):
    d = Path(project) / "docs/project/decisions.md"
    text = d.read_text(encoding="utf-8") if d.is_file() else ""
    return [(m.group(1), m.group(0)) for m in SECTION.finditer(text)]


def resolving(project, iid):
    return [(did, body) for did, body in entries(project)
            if re.search(rf"^Resolves:\s*{re.escape(iid)}\b", body, re.M)]


def entry_problems(project, iid, did, body, words=None):
    """What is wrong with decision entry did as the resolution of inbox item iid."""
    out = []
    if not VERDICT.search(body):
        out.append(f"{did} resolves {iid} but has no Verdict line (ADOPT, ADOPT-PART, RESHAPE, PLACE M<k>, REJECT)")
    routed = re.search(r"^Routed:\s*(.+)$", body, re.M)
    verdict = VERDICT.search(body)
    if not routed:
        out.append(f"{did} resolves {iid} but has no Routed line (where each adopted part went, or none)")
    else:
        contract = re.search(r"\b(intent\.md|milestones\.md)\b", routed.group(1))
        declined = verdict and verdict.group(1) != "ADOPT"
        if contract or declined:
            from rulings import entry_proven  # noqa: E402
            ok, why = entry_proven(project, did)
            if not ok:
                what = "changes the intent or a milestone contract" if contract else \
                    f"is a {verdict.group(1)} (declining or reshaping input is the owner's call)"
                out.append(f"{did} {what} but is not a proven owner ruling: {why}")
    quote = re.search(r"^Item:\s*\"(.+)\"\s*$", body, re.M)
    if not quote:
        out.append(f"{did} resolves {iid} but does not quote it (Item: \"<the item's words>\")")
    elif words is not None and norm(quote.group(1)) != words:
        out.append(f"{did} quotes {iid} as \"{norm(quote.group(1))[:50]}\", but the item says \"{words[:50]}\"")
    return out


def cmd_add(project, opts):
    kind = opts.get("--kind")
    if kind not in KINDS or not opts.get("--from") or not (opts.get("--text") or opts.get("--source")):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text(encoding="utf-8") if p.is_file() else HEADER
    n = next_number(text)
    if n is None:
        print("FAIL   inbox       docs/project/inbox.md has no 'Next: IN-<nnn>' line; restore it before adding")
        return 1
    iid = f"IN-{n:03d}"
    today = datetime.date.today().isoformat()
    words = opts.get("--text") or ""
    title = opts.get("--title") or (norm(words)[:60] if words else opts["--source"])
    lines = [f"## {iid} · {today} · {title}",
             f"From: {opts['--from']}" + (f" · via {opts['--via']}" if opts.get("--via") else "") + f" · kind: {kind}"]
    if words:
        lines += ["Text:"] + [f"> {l}" if l.strip() else ">" for l in words.strip().splitlines()]
    if opts.get("--source"):
        lines.append(f"Source: {opts['--source']}")
    lines.append("Status: open")
    text = re.sub(r"^Next:\s*IN-\d+", f"Next: IN-{n + 1:03d}", text, count=1, flags=re.M)
    p.write_text(text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(iid)
    return 0


def open_items(project):
    p = path(project)
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    out = []
    for iid, block in items(text).items():
        head = block.splitlines()[0]
        status = re.search(r"^Status:\s*(.+)$", block, re.M)
        frm = re.search(r"^From:\s*(.+)$", block, re.M)
        out.append({"id": iid, "date": head.split(" · ")[1] if " · " in head else "",
                    "title": head.split(" · ", 2)[-1], "from": frm.group(1) if frm else "",
                    "status": status.group(1).strip() if status else "open"})
    return out


def cmd_list(project, as_json):
    rows = open_items(project)
    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for r in rows:
            print(f"{r['id']} · {r['date']} · {r['title']} · from {r['from']} · {r['status']}")
        print(f"inbox: {len(rows)} open item(s)")
    return 0


def cmd_resolve(project, iid, did):
    p = path(project)
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    block = items(text).get(iid)
    if block is None:
        print(f"FAIL   inbox       {iid} is not open in docs/project/inbox.md")
        return 1
    body = dict(entries(project)).get(did)
    if body is None or not re.search(rf"^Resolves:\s*{re.escape(iid)}\b", body, re.M):
        print(f"FAIL   inbox       {did} is not in decisions.md with 'Resolves: {iid}'; write the decision first")
        return 1
    problems = entry_problems(project, iid, did, body, item_words(block))
    if problems:
        for pr in problems:
            print(f"FAIL   inbox       {pr}")
        return 1
    p.write_text(re.sub(r"\n{3,}", "\n\n", text.replace(block, "")).rstrip("\n") + "\n", encoding="utf-8")
    print(f"PASS   inbox       {iid} resolved by {did} and cleared from the inbox")
    return 0


def cmd_check(project):
    p = path(project)
    if not p.is_file():
        print("SKIP   inbox       no docs/project/inbox.md")
        return 0
    text = p.read_text(encoding="utf-8")
    n = next_number(text)
    if n is None:
        print("FAIL   inbox       no 'Next: IN-<nnn>' line, so dropped items cannot be told apart")
        return 1
    listed = items(text)
    fails = 0
    for k in range(1, n):
        iid = f"IN-{k:03d}"
        res = resolving(project, iid)
        if iid in listed and res:
            print(f"FAIL   inbox       {iid} is resolved by {res[0][0]} but still listed in the inbox")
            fails += 1
        elif iid not in listed and not res:
            print(f"FAIL   inbox       {iid} left the inbox without a decision entry (Resolves: {iid})")
            fails += 1
        elif res:
            # decisions.md is append-only: a later entry for the same item supersedes an earlier attempt
            for did, body in res[-1:]:
                for pr in entry_problems(project, iid, did, body):
                    print(f"FAIL   inbox       {pr}")
                    fails += 1
    beyond = [i for i in listed if int(i[3:]) >= n]
    if beyond:
        print(f"FAIL   inbox       numbered at or past Next (IN-{n:03d}): {', '.join(beyond)}; add items with inbox.py add")
        fails += 1
    if not fails:
        print(f"PASS   inbox       {n - 1} item(s) accounted for: {len(listed)} open, {n - 1 - len(listed)} resolved")
        if listed:
            print(f"WARN   inbox       {len(listed)} open: {', '.join(listed)} (weigh them with /inbox review)")
    return 1 if fails else 0


def main(argv):
    if len(argv) < 2 or argv[0] not in ("add", "list", "resolve", "check"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, project, rest = argv[0], Path(argv[1]), argv[2:]
    if cmd == "add":
        keys = ("--from", "--kind", "--text", "--source", "--via", "--title")
        opts = {rest[i]: rest[i + 1] for i in range(len(rest) - 1) if rest[i] in keys}
        return cmd_add(project, opts)
    if cmd == "list":
        return cmd_list(project, "--json" in rest)
    if cmd == "resolve":
        if len(rest) != 3 or rest[1] != "--decision" or not re.fullmatch(r"IN-\d{3,}", rest[0]):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        return cmd_resolve(project, rest[0], rest[2])
    return cmd_check(project)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
