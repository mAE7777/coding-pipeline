#!/usr/bin/env python3
"""Check a milestones.md file against the milestone format rules.

Usage: milestone_lint.py [path/to/milestones.md] [--no-history] [--intent path/to/intent.md]
       milestone_lint.py [path/to/milestones.md] --contract-hash M<k>

Every check prints PASS, FAIL, or WARN with a reason. Exit 0 = no FAIL, 1 = at least one FAIL,
2 = bad invocation. Checks:
  - structure and fields of every milestone (status, promise, Carries, Mechanisms, numbered demo ending,
    done examples, checkpoints, parked items, non-goals, readiness, wiring rows and their statuses);
  - with intent.md (the --intent path, or intent.md next to this file; re-freezes applied): every I-Dn is
    carried or a named non-goal, and every Mechanisms name is a mechanism card;
  - accepted milestones: an owner acceptance in decisions.md ("Accept M<k> · contract <hash>") that
    rulings.py proves, whose hash equals the current contract (Promise, Carries, Demo ending, Done
    examples), unless a later "Superseded: D-<nnn>" line names another proven ruling;
  - contract tests named in interfaces.md exist once their milestone reaches the gate;
  - the idea-anchor closure and blueprint parts (closure.py), against truth/idea-anchor.md and a
    blueprint when the project has them;
  - with git and the file tracked at HEAD: no milestone or sub-ID was removed or renumbered.
--contract-hash prints the contract hash the acceptance entry records.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import closure  # noqa: E402

STATUSES = {"planned", "building", "gate", "changes", "accepted", "dropped"}
NOT_A_STATE = re.compile(r"\b(later|v2|future version|someday|tbd|to be decided)\b", re.I)
MILESTONE_HEAD = re.compile(r"^## (M\d+) · (.+?)\s*$")
CONTRACT_FIELDS = ("Promise:", "Carries:", "Demo ending:", "Done examples:")
SUPERSEDED = re.compile(r"^Superseded:\s*(D-\d+)", re.M)
ACCEPT = re.compile(r"Accept (M\d+) · contract ([0-9a-f]{16})")
WIRING_STATUS = {"built", "validated", "wired", "proven", "parked"}

results = []


def report(status, check, detail):
    results.append((status, check, detail))


def split_sections(text):
    """Return (milestones dict id -> list of lines, None, order of ids, duplicates)."""
    milestones, order, dupes = {}, [], []
    current = None
    for line in text.splitlines():
        m = MILESTONE_HEAD.match(line)
        if m:
            mid = m.group(1)
            if mid in milestones:
                dupes.append(mid)
            milestones[mid] = [line]
            order.append(mid)
            current = milestones[mid]
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is not None:
            current.append(line)
    return milestones, None, order, dupes


def block(lines, label):
    """Lines after a 'Label:' line until the next blank-line-separated label."""
    out, inside = [], False
    for line in lines:
        if line.startswith(label):
            inside = True
            rest = line[len(label):].strip()
            if rest:
                out.append(rest)
            continue
        if inside:
            if re.match(r"^[A-Z][A-Za-z -]+:( |$)", line) and not line.startswith("- "):
                break
            if line.strip():
                out.append(line.strip())
    return out


def field(lines, label):
    for line in lines:
        if line.startswith(label):
            return line[len(label):].strip()
    return None


def contract_text(lines):
    parts = []
    for label in CONTRACT_FIELDS:
        parts.append(label + "\n" + "\n".join(block(lines, label)))
    return "\n".join(parts)


def contract_hash(lines):
    return hashlib.sha256(contract_text(lines).encode("utf-8")).hexdigest()[:16]


def wiring_rows(lines):
    rows, inside = [], False
    for line in lines:
        if line.startswith("Wiring:"):
            inside = True
            continue
        if inside:
            s = line.strip()
            if not s.startswith("|"):
                if s:
                    break
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and (cells[0].lower() == "component" or set(cells[0]) <= set("-: ")):
                continue
            rows.append(cells)
    return rows


def check_milestone(mid, lines):
    status = field(lines, "Status:")
    if status is None:
        report("FAIL", mid, "no 'Status:' line")
    elif status.split()[0].lower() not in STATUSES:
        report("FAIL", mid, f"status '{status}' is not one of {sorted(STATUSES)}")
    dropped = status is not None and status.split()[0].lower() == "dropped"

    promise = field(lines, "Promise:")
    if not dropped and (not promise or promise.startswith("<")):
        report("FAIL", mid, "no promise written")

    carries = field(lines, "Carries:")
    if not dropped and carries is None:
        report("FAIL", mid, "no 'Carries:' line (the intent.md done examples it carries, or none)")
    elif carries and carries.lower() != "none" and not re.search(r"\bI-D\d+\b", carries) \
            and not carries.startswith("<"):
        report("FAIL", mid, f"'Carries:' names no I-D example: {carries[:60]}")

    demo = [l for l in block(lines, "Demo ending:") if re.match(r"^\d+\.\s+\S", l)]
    if not dropped and not demo:
        report("FAIL", mid, "no numbered demo ending (a milestone that cannot be demonstrated is not a milestone)")

    done = block(lines, "Done examples:")
    ids = re.findall(r"\b(M\d+)\.D\d+\b", "\n".join(done))
    if not dropped and not ids:
        report("FAIL", mid, "no done examples with IDs like " + mid + ".D1")
    for owner in set(ids):
        if owner != mid:
            report("FAIL", mid, f"done example ID belongs to {owner}")
    for line in done:
        if re.search(r"\bM\d+\.D\d+\b", line) and "Example:" not in line and "example:" not in line:
            report("WARN", mid, f"done example has no concrete example: {line[:70]}")

    checkpoints = re.findall(r"\b(M\d+)\.C\d+\b", "\n".join(block(lines, "Checkpoints:")))
    for owner in set(checkpoints):
        if owner != mid:
            report("FAIL", mid, f"checkpoint ID belongs to {owner}")

    for item in block(lines, "Parked:"):
        if item.lower() in ("- none", "none"):
            continue
        if item.startswith("- ") and ("re-enable:" not in item or not re.search(r"owner:\s*M\d+", item)):
            report("FAIL", mid, f"parked item lacks a re-enable condition or owning milestone: {item[:70]}")

    for item in block(lines, "Named non-goals:"):
        if item.startswith("- ") and item.lower() != "- none" and "reason:" not in item:
            report("FAIL", mid, f"named non-goal without a reason: {item[:70]}")

    for label in ("In scope:", "Named non-goals:", "Parked:"):
        for item in block(lines, label):
            if NOT_A_STATE.search(item):
                report("FAIL", mid, f"'{NOT_A_STATE.search(item).group(0)}' is not a state: {item[:70]}")

    if not any(l.startswith("Readiness:") for l in lines):
        report("FAIL", mid, "no 'Readiness:' line")

    if not dropped and field(lines, "Mechanisms:") is None:
        report("FAIL", mid, "no 'Mechanisms:' line (the intent.md mechanism cards it exercises, or none)")

    state = status.split()[0].lower() if status else ""
    for cells in wiring_rows(lines):
        if len(cells) < 7:
            report("FAIL", mid, f"wiring row has {len(cells)} cells, needs 7: {' | '.join(cells)[:60]}")
            continue
        if cells[0].startswith("<"):
            continue
        st = cells[6].lower()
        if st not in WIRING_STATUS:
            report("FAIL", mid, f"wiring row '{cells[0]}' status '{cells[6]}' is not one of {sorted(WIRING_STATUS)}")
        elif state in ("gate", "accepted") and st not in ("proven", "parked"):
            report("FAIL", mid, f"at {state}, wiring row '{cells[0]}' is '{st}' (every row is proven or parked)")

    placeholders = [l for l in lines if re.search(r"<[a-z][^>]{2,}>", l)]
    if placeholders and not dropped:
        report("WARN", mid, f"{len(placeholders)} template placeholder line(s) left, first: {placeholders[0][:60]}")
    return status


def project_root(path):
    p = path.resolve()
    return p.parents[2] if p.parent.name == "project" and p.parent.parent.name == "docs" else p.parent


def check_closure(text, root):
    anchor = root / "truth/idea-anchor.md"
    blueprint, problem = closure.find_blueprint(root)
    if problem:
        report("FAIL", "closure", problem)
    for problem in closure.problems(text, anchor.read_text(encoding="utf-8") if anchor.is_file() else None,
                                    blueprint.read_text(encoding="utf-8") if blueprint else None):
        report("FAIL", "closure", problem)


def check_mechanisms(effective, milestones):
    cards = set(effective.get("mechanisms") or [])
    for mid, lines in milestones.items():
        names = field(lines, "Mechanisms:")
        if not names or names.lower() == "none" or names.startswith("<"):
            continue
        for name in [n.strip() for n in names.split(",") if n.strip()]:
            if name not in cards:
                report("FAIL", mid, f"Mechanisms names '{name}', which is not a mechanism card in intent.md")


def decision_sections(root):
    d = root / "docs/project/decisions.md"
    if not d.is_file():
        return {}
    text = d.read_text(encoding="utf-8")
    return {m.group(1): m.group(0) for m in re.finditer(r"^## (D-\d{3,})\b.*?(?=^## D-\d{3,}\b|\Z)", text, re.M | re.S)}


def latest_accept_ready(root, mid):
    """The fingerprint of the milestone's latest ACCEPT-READY gate round in .evidence, or None."""
    rounds = sorted((root / ".evidence/gate" / mid).glob("r*"),
                    key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else -1)
    for r in reversed(rounds):
        try:
            v = json.loads((r / "verdict.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if v.get("verdict") == "ACCEPT-READY":
            return v.get("fingerprint")
    return None


def check_acceptance(milestones, root):
    from rulings import entry_proven  # noqa: E402
    sections = decision_sections(root)
    for mid, lines in milestones.items():
        status = (field(lines, "Status:") or "").split()[:1]
        if not status or status[0].lower() != "accepted":
            continue
        entries = [(did, h) for did, body in sections.items() for m, h in ACCEPT.findall(body) if m == mid]
        if not entries:
            report("FAIL", mid, "accepted without an owner acceptance entry ('Accept " + mid +
                   " · contract <hash>') in decisions.md")
            continue
        did, recorded = entries[-1]
        ok, why = entry_proven(root, did)
        if not ok:
            report("FAIL", mid, f"acceptance {did} is not a proven owner ruling: {why}")
            continue
        fp = re.search(r"fingerprint (\S+)", sections[did])
        gated = latest_accept_ready(root, mid)
        if not fp:
            report("FAIL", mid, f"acceptance {did} names no fingerprint (the candidate the owner accepted)")
        elif gated is None:
            report("WARN", mid, f"acceptance {did} names {fp.group(1)}, but no ACCEPT-READY round of {mid} is on this "
                   "machine to compare it with")
        elif fp.group(1) != gated:
            report("FAIL", mid, f"acceptance {did} names fingerprint {fp.group(1)}, but the latest ACCEPT-READY round "
                   f"of {mid} checked {gated}: the owner accepted something other than what passed the gate")
        current = contract_hash(lines)
        if current != recorded:
            sups = [s for s in SUPERSEDED.findall("\n".join(lines))
                    if int(s[2:]) > int(did[2:]) and entry_proven(root, s)[0]]
            if sups:
                report("WARN", mid, f"contract changed after acceptance {did}, superseded by {', '.join(sups)}")
            else:
                report("FAIL", mid, f"contract changed after acceptance {did} (hash {current} != {recorded}) "
                       "without a 'Superseded: D-<nnn>' line naming a proven owner ruling")


def check_contract_tests(milestones, root):
    interfaces = root / "docs/project/interfaces.md"
    if not interfaces.is_file():
        return
    for path, owner in re.findall(r"^Contract test:\s*`?([^`\s(]+)`?\s*\(owned by (M\d+)", interfaces.read_text(
            encoding="utf-8"), flags=re.M):
        lines = milestones.get(owner)
        if lines is None:
            report("FAIL", "interfaces", f"contract test {path} is owned by {owner}, which is not a milestone")
            continue
        status = (field(lines, "Status:") or "").split()[:1]
        if status and status[0].lower() in ("gate", "accepted") and not (root / path).exists():
            report("FAIL", "interfaces", f"{owner} is at {status[0]} and its contract test {path} does not exist")


def git_head_version(path):
    try:
        root = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True).stdout.strip()
        rel = path.resolve().relative_to(Path(root).resolve())
        out = subprocess.run(["git", "-C", root, "show", f"HEAD:{rel.as_posix()}"],
                             capture_output=True, text=True)
        return out.stdout if out.returncode == 0 else None
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None


def check_history(old_text, new_ms):
    old_ms, _, _, _ = split_sections(old_text)
    old_ids = set(old_ms)
    for mid in sorted(old_ids - set(new_ms)):
        report("FAIL", "history", f"{mid} existed at HEAD and is gone (mark it 'Status: dropped' instead)")
    all_old = set(re.findall(r"\bM\d+\.[DC]\d+\b", old_text))
    all_new = set(re.findall(r"\bM\d+\.[DC]\d+\b", "\n".join("\n".join(v) for v in new_ms.values())))
    for sub in sorted(all_old - all_new):
        report("FAIL", "history", f"{sub} existed at HEAD and is gone (IDs are never renumbered)")
    for mid, lines in old_ms.items():
        old_status = (field(lines, "Status:") or "").split()[:1]
        if old_status and old_status[0].lower() == "accepted" and mid in new_ms:
            if contract_text(lines) != contract_text(new_ms[mid]):
                old_sup = set(SUPERSEDED.findall("\n".join(lines)))
                new_sup = set(SUPERSEDED.findall("\n".join(new_ms[mid])))
                if not (new_sup - old_sup):
                    report("FAIL", "history", f"{mid} was accepted and its contract changed without a new "
                           "'Superseded: D-<nnn>' line")
                else:
                    report("WARN", "history", f"{mid} contract superseded by {', '.join(sorted(new_sup - old_sup))}; "
                           "confirm the owner's ruling is in decisions.md")


def check_carried(effective, milestones):
    wanted = set(effective.get("done_examples") or {})
    carried, non_goals = set(), "\n".join("\n".join(block(v, "Named non-goals:")) for v in milestones.values())
    for lines in milestones.values():
        carried |= set(re.findall(r"\bI-D\d+[a-z]?\b", field(lines, "Carries:") or ""))
    for iid in sorted(wanted - carried):
        if iid not in non_goals:
            report("FAIL", "carried", f"{iid} from intent.md is carried by no milestone and is not a named non-goal")
    for iid in sorted(carried - wanted):
        report("FAIL", "carried", f"{iid} is carried but does not exist in intent.md")


def main(argv):
    if "--contract-hash" in argv:
        i = argv.index("--contract-hash")
        rest = [a for j, a in enumerate(argv) if j not in (i, i + 1)]
        path = Path(rest[0] if rest else "docs/project/milestones.md")
        milestones, _, _, _ = split_sections(path.read_text(encoding="utf-8"))
        mid = argv[i + 1] if i + 1 < len(argv) else ""
        if mid not in milestones:
            print(f"milestone_lint: no milestone {mid}", file=sys.stderr)
            return 2
        print(contract_hash(milestones[mid]))
        return 0
    intent_arg = None
    if "--intent" in argv:
        i = argv.index("--intent")
        if i + 1 >= len(argv):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        intent_arg = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    if len(args) > 1 or flags - {"--no-history"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(args[0] if args else "docs/project/milestones.md")
    if not path.is_file():
        print(f"milestone_lint: no such file: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    milestones, closure, order, dupes = split_sections(text)
    if not milestones:
        report("FAIL", "structure", "no '## M<n> · <name>' sections found")
    for mid in dupes:
        report("FAIL", "structure", f"{mid} appears more than once")
    for mid in order:
        check_milestone(mid, milestones[mid])
    root = project_root(path)
    check_closure(text, root)
    intent_path = Path(intent_arg) if intent_arg else path.parent / "intent.md"
    if intent_path.is_file():
        from intent_lock import effective  # noqa: E402
        eff = effective(intent_path.read_text(encoding="utf-8"))
        check_carried(eff, milestones)
        check_mechanisms(eff, milestones)
    elif intent_arg:
        report("FAIL", "carried", f"intent file not found: {intent_arg}")
    check_acceptance(milestones, root)
    check_contract_tests(milestones, root)
    if "--no-history" not in flags:
        old = git_head_version(path)
        if old is None:
            report("WARN", "history", "not tracked at HEAD (or no git): ID stability not checked")
        else:
            check_history(old, milestones)
    fails = sum(1 for r in results if r[0] == "FAIL")
    if not any(r[0] in ("FAIL", "WARN") for r in results):
        report("PASS", "milestones", f"{len(milestones)} milestone(s) well-formed")
    for status, check, detail in results:
        print(f"{status:<5}  {check:<10}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
