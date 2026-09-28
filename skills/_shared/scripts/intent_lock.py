#!/usr/bin/env python3
"""Lock, verify, and read the effective content of docs/project/intent.md.

Usage:
  intent_lock.py hash <intent.md>
  intent_lock.py lint <intent.md>
  intent_lock.py stamp <intent.md> --ruling D-<nnn> [--project <dir>]
  intent_lock.py verify <intent.md> [--project <dir>]
  intent_lock.py effective <intent.md>

The locked text runs from the "## Goal" line up to, not including, "## Re-freeze log"; the status line
above it and the log below it are outside the hash, so the stamp can record re-freezes without changing
what was locked. The status line is "Status: draft" before the lock and afterwards
  Locked by the owner <YYYY-MM-DD> · hash <16 hex> · ruling D-<nnn> · re-freezes <n>

lint     the file is ready to lock: every section present and filled, a "Persona (blind):" line that
         shares no content word with the goal, identity, load-bearing behavior, or done examples (so an
         evaluator that must guess the purpose cannot read it off the persona), every done example with a
         concrete "Example:", every must-not-lose item ending in "· check: ..." or
         "· not code-checkable (...)".
stamp    lint passes and the ruling is proven (rulings.py), then writes the status line.
verify   the hash still matches the stamp; every re-freeze entry names a proven owner ruling and the
         stamp counts them. A mismatch means the locked text was edited: FAIL.
effective  JSON of the intent after applying the re-freeze log: goal, persona_blind, done examples,
         must-not-lose items, mechanism names. Re-freeze grammar inside "### RF-<n> · <date> · D-<nnn>":
           Supersedes I-D2 with I-D2a: <statement>
           Adds I-D5: <statement>          (also L-nn)
           Drops I-D3 (reason: ...)        (also L-nn)

Exit 0 on success, 1 on a FAIL, 2 on bad usage.
"""
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ("## Goal", "## Identity and promise", "## Who", "## Load-bearing behavior", "## Done examples",
            "## Mechanism cards", "## Must not lose", "## Re-freeze log")
STAMP = re.compile(r"^Locked by the owner (\d{4}-\d{2}-\d{2}) · hash ([0-9a-f]{16}) · ruling (D-\d{3,}) · "
                   r"re-freezes (\d+)\s*$", re.M)
STOP = set("the a an and or of to in on for with by at is are be as it this that from when if then its their they "
           "them you your we our can will not no any each into than so who uses use using user users person people "
           "someone comfortable basic daily skill level surface phone phones laptop desktop web browser app mobile "
           "adult adults new experienced".split())


def locked_region(text):
    start = text.find("## Goal")
    end = text.find("## Re-freeze log")
    if start < 0 or end < 0 or end < start:
        return None
    region = text[start:end]
    return "\n".join(line.rstrip() for line in region.replace("\r\n", "\n").split("\n")).strip() + "\n"


def intent_hash(text):
    region = locked_region(text)
    return None if region is None else hashlib.sha256(region.encode("utf-8")).hexdigest()[:16]


def section(text, heading):
    m = re.search(rf"^{re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


CJK_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+")
CJK_STOP = set("\u7684\u4e86\u662f\u5728\u548c\u4e0e\u53ca\u6216\u4e00\u4e2a\u6211\u4f60\u4ed6\u5979\u5b83\u4eec\u8fd9\u90a3\u6709\u4e5f\u90fd\u5c31\u8981\u4f1a\u80fd\u53ef\u4ee5\u4e3a\u7740\u8fc7\u628a\u88ab\u8ba9\u7ed9\u5bf9\u4ece\u5230\u800c\u4e14\u4f46\u5f88\u66f4\u6700\u53c8\u518d\u8fd8\u4e4b\u5176\u6240")


def words(s):
    """Comparable words: English words (stemmed, stop words out), and for Chinese, Japanese, or Korean text the
    two-character pairs that hold no function character, so a persona written in Chinese is checked too."""
    text = re.sub(r"<!--.*?-->", "", s, flags=re.S).lower()
    out = set()
    for w in re.findall(r"[a-z]+", text):
        if len(w) > 3 and w not in STOP:
            out.add(re.sub(r"(ies|es|s|ing|ed)$", "", w))
    for run in CJK_RUN.findall(text):
        for i in range(len(run) - 1):
            pair = run[i:i + 2]
            if not (set(pair) & CJK_STOP):
                out.add(pair)
    return out


def persona_blind(text):
    m = re.search(r"^Persona \(blind\):\s*(.+)$", text, flags=re.M)
    return m.group(1).strip() if m else None


def lint(text):
    problems = []
    for h in REQUIRED:
        if not re.search(rf"^{re.escape(h)}\s*$", text, flags=re.M):
            problems.append(f"missing section '{h}'")
    region = locked_region(text) or ""
    ph = [l for l in region.splitlines() if re.search(r"<[a-z][^>]{2,}>", l) and not l.strip().startswith("<!--")]
    if ph:
        problems.append(f"{len(ph)} template placeholder line(s) left, first: {ph[0][:60]}")
    persona = persona_blind(text)
    if not persona:
        problems.append("no 'Persona (blind):' line under ## Who")
    else:
        purpose = " ".join(section(text, h) for h in ("## Goal", "## Identity and promise", "## Load-bearing behavior",
                                                      "## Done examples"))
        shared = sorted(words(persona) & words(purpose))
        if purpose.strip() and not words(purpose):
            problems.append("the goal and examples yield no comparable words, so the blind persona cannot be checked")
        if shared:
            problems.append(f"the blind persona shares purpose words with the goal or examples: {', '.join(shared[:6])}")
    for line in section(text, "## Done examples").splitlines():
        if re.match(r"^- I-D\d+", line) and "Example:" not in line:
            problems.append(f"done example without a concrete example: {line[:60]}")
    for line in section(text, "## Must not lose").splitlines():
        if re.match(r"^- L-\d+", line) and not re.search(r"· (check: \S|not code-checkable \()", line):
            problems.append(f"must-not-lose item without '· check: ...' or '· not code-checkable (...)': {line[:60]}")
    return problems


def ruling_ok(project, ruling):
    sys.path.insert(0, str(HERE))
    from rulings import entry_proven  # noqa: E402
    return entry_proven(project, ruling)


def refreeze_entries(text):
    log = text[text.find("## Re-freeze log"):] if "## Re-freeze log" in text else ""
    log = re.sub(r"<!--.*?-->", "", log, flags=re.S)
    return re.findall(r"^### (RF-\d+) · (\d{4}-\d{2}-\d{2}) · (D-\d{3,})(.*?)(?=^### RF-|\Z)", log, flags=re.M | re.S)


def effective(text):
    done = dict(re.findall(r"^- (I-D\d+[a-z]?)\s+(.+)$", section(text, "## Done examples"), flags=re.M))
    keep = dict(re.findall(r"^- (L-\d+[a-z]?)\s+(.+)$", section(text, "## Must not lose"), flags=re.M))
    for _, _, _, body in refreeze_entries(text):
        for old, new, stmt in re.findall(r"^Supersedes (I-D\d+[a-z]?|L-\d+[a-z]?) with (I-D\d+[a-z]?|L-\d+[a-z]?):\s*(.+)$",
                                         body, flags=re.M):
            target = done if old.startswith("I-D") else keep
            target.pop(old, None)
            target[new] = stmt
        for new, stmt in re.findall(r"^Adds (I-D\d+[a-z]?|L-\d+[a-z]?):\s*(.+)$", body, flags=re.M):
            (done if new.startswith("I-D") else keep)[new] = stmt
        for old in re.findall(r"^Drops (I-D\d+[a-z]?|L-\d+[a-z]?)\b", body, flags=re.M):
            (done if old.startswith("I-D") else keep).pop(old, None)
    goal = section(text, "## Goal").strip()
    mechanisms = re.findall(r"^### (.+?)\s*$", section(text, "## Mechanism cards"), flags=re.M)
    return {"goal": goal, "persona_blind": persona_blind(text), "done_examples": done, "must_not_lose": keep,
            "mechanisms": mechanisms, "hash": intent_hash(text)}


def main(argv):
    if len(argv) < 2 or argv[0] not in ("hash", "lint", "stamp", "verify", "effective"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, path = argv[0], Path(argv[1])
    if not path.is_file():
        print(f"intent_lock: no such file: {path}", file=sys.stderr)
        return 2
    opts = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1) if argv[i] in ("--ruling", "--project")}
    project = Path(opts.get("--project") or path.resolve().parents[2])
    text = path.read_text(encoding="utf-8")
    if cmd == "hash":
        h = intent_hash(text)
        if h is None:
            print("FAIL   intent      no '## Goal' ... '## Re-freeze log' region")
            return 1
        print(h)
        return 0
    if cmd == "effective":
        print(json.dumps(effective(text), indent=2, ensure_ascii=False))
        return 0
    if cmd == "lint":
        problems = lint(text)
        for p in problems:
            print(f"FAIL   intent      {p}")
        if not problems:
            print("PASS   intent      ready to lock")
        return 1 if problems else 0
    if cmd == "stamp":
        ruling = opts.get("--ruling")
        if not ruling:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        problems = lint(text)
        if problems:
            for p in problems:
                print(f"FAIL   intent      {p}")
            return 1
        ok, detail = ruling_ok(project, ruling)
        if not ok:
            print(f"FAIL   intent      the lock ruling {ruling} is not a proven owner ruling\n{detail}")
            return 1
        today = datetime.date.today().isoformat()
        line = f"Locked by the owner {today} · hash {intent_hash(text)} · ruling {ruling} · re-freezes 0"
        if re.search(r"^Status: draft\s*$", text, flags=re.M):
            text = re.sub(r"^Status: draft\s*$", line, text, count=1, flags=re.M)
        elif STAMP.search(text):
            print("FAIL   intent      already locked; a change goes through a re-freeze entry")
            return 1
        else:
            print("FAIL   intent      no 'Status: draft' line to stamp")
            return 1
        path.write_text(text, encoding="utf-8")
        print(f"PASS   intent      {line}")
        return 0
    # verify
    m = STAMP.search(text)
    if not m:
        print("FAIL   intent      not locked (no 'Locked by the owner ...' line)")
        return 1
    fails = []
    if m.group(2) != intent_hash(text):
        fails.append(f"the locked text changed after the lock (hash {intent_hash(text)} != stamped {m.group(2)}); "
                     "restore it and record the change as a re-freeze")
    entries = refreeze_entries(text)
    if int(m.group(4)) != len(entries):
        fails.append(f"stamp counts {m.group(4)} re-freezes, the log has {len(entries)}")
    for rid, _, did, _ in entries:
        ok, _ = ruling_ok(project, did)
        if not ok:
            fails.append(f"{rid} cites {did}, which is not a proven owner ruling")
    for f in fails:
        print(f"FAIL   intent      {f}")
    if not fails:
        print(f"PASS   intent      locked {m.group(1)} · hash {m.group(2)} · {len(entries)} re-freeze(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
