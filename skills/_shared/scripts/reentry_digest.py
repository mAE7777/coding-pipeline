#!/usr/bin/env python3
"""Print what a session needs to pick the work up again after a compaction, read from the record files alone.

Usage: reentry_digest.py <project>

The project is the folder holding docs/project/state.md (a folder inside it works too). Printed, each part headed
by its file and section:
  state.md       Milestone, Understanding, Open, In flight, Failures, Blockers, Next step, Eliminated approaches
                 ("none recorded" for a section the file does not have)
  milestones.md  the current milestone's whole section (the one state.md's Milestone line names, else the first
                 one not accepted or dropped)
  intent.md      with re-freezes applied (intent_lock.py effective): the Goal, the Must not lose items, the done
                 examples the milestone carries, and the mechanism cards it names
  decisions.md   the headings of the last 5 entries
It ends with the paths of the full files, to read when a detail is not in the digest. Template comments are left
out. The reload gate counts running this script as reading state.md, intent.md, and milestones.md.

Exit 0 when the digest is printed, 1 when the folder has no docs/project/state.md, 2 on bad usage.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intent_lock import effective  # noqa: E402

STATE_SECTIONS = ("Milestone", "Understanding", "Open", "In flight", "Failures", "Blockers", "Next step",
                  "Eliminated approaches")
MILESTONE = re.compile(r"^## (M\d+) · ([^\n]+?)[ \t]*$(.*?)(?=^## |\Z)", re.M | re.S)
CARD = re.compile(r"^### ([^\n]+?)[ \t]*$.*?(?=^### |\Z)", re.M | re.S)
DONE_STATES = ("accepted", "dropped")
LAST_DECISIONS = 5


def clean(text):
    """The text without template comments and with blank runs closed up."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def section(text, heading):
    """The body of '## <heading>', or None when there is no such section."""
    m = re.search(rf"^## {re.escape(heading)}[ \t]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return clean(m.group(1)) if m else None


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def find_project(start):
    start = Path(start).expanduser().resolve()
    for c in (start, *start.parents):
        if (c / "docs/project/state.md").is_file():
            return c
    return None


def current_milestone(state, milestones):
    """(id, name, body, how it was chosen) of the milestone to show, or None."""
    found = {m.group(1): (m.group(1), m.group(2), m.group(3)) for m in MILESTONE.finditer(milestones or "")}
    named = re.search(r"\bM\d+\b", section(state, "Milestone") or "")
    if named and named.group(0) in found:
        return found[named.group(0)] + ("named in state.md's Milestone section",)
    for mid, name, body in found.values():
        status = re.search(r"^Status:\s*(\S+)", body, re.M)
        if not status or status.group(1).lower() not in DONE_STATES:  # milestone_lint reads it without case
            why = (f"state.md names {named.group(0)}, which milestones.md does not have; " if named else
                   "state.md names no milestone; ") + "this is the first one not accepted or dropped"
            return mid, name, body, why
    return None


def field(body, label):
    m = re.search(rf"^{re.escape(label)}\s*(.*)$", body, re.M)
    return m.group(1).strip() if m else ""


def cards(intent):
    """{name: the card's whole text} from intent.md's Mechanism cards section."""
    body = section(intent, "Mechanism cards") or ""
    return {m.group(1).strip(): clean(m.group(0)) for m in CARD.finditer(body)}


def carried_examples(ids, done):
    out = []
    for iid in ids:
        if iid in done:
            out.append(f"- {iid} {done[iid]}")
            continue
        later = sorted(k for k in done if re.fullmatch(rf"{re.escape(iid)}[a-z]", k))
        if later:
            out += [f"- {k} {done[k]} (supersedes {iid})" for k in later]
        else:
            out.append(f"- {iid}: not in the effective intent (dropped by a re-freeze, or never written)")
    return out


def digest(root):
    docs = root / "docs/project"
    paths = {name: docs / name for name in ("state.md", "milestones.md", "intent.md", "decisions.md")}
    texts = {name: read(p) for name, p in paths.items()}
    state, milestones, intent, decisions = (texts[n] for n in ("state.md", "milestones.md", "intent.md", "decisions.md"))
    out = [f"# Re-entry digest · {root.name}", ""]

    for name in STATE_SECTIONS:
        body = section(state or "", name)
        out += [f"## docs/project/state.md · {name}", body if body else ("(empty)" if body == "" else "none recorded"), ""]

    current = current_milestone(state or "", milestones) if milestones is not None else None
    if milestones is None:
        out += ["## docs/project/milestones.md", "not found", ""]
    elif current is None:
        out += ["## docs/project/milestones.md · current milestone", "none recorded (no milestone section to show)", ""]
    else:
        mid, name, body, why = current
        out += [f"## docs/project/milestones.md · {mid} · {name} ({why})", clean(body), ""]

    if intent is None:
        out += ["## docs/project/intent.md", "not found", ""]
    else:
        eff = effective(intent)
        refreezes = len(re.findall(r"^### RF-\d+", intent, re.M))
        applied = f" ({refreezes} re-freeze(s) applied)" if refreezes else ""
        out += ["## docs/project/intent.md · Goal", clean(eff["goal"]) or "none recorded", ""]
        keep = [f"- {k} {v}" for k, v in eff["must_not_lose"].items()]
        out += [f"## docs/project/intent.md · Must not lose{applied}", "\n".join(keep) or "none recorded", ""]
        if current:
            mid, _, body, _ = current
            ids = re.findall(r"\bI-D\d+[a-z]?\b", field(body, "Carries:"))
            out += [f"## docs/project/intent.md · Done examples {mid} carries{applied}",
                    "\n".join(carried_examples(ids, eff["done_examples"])) or "none (Carries names no I-D example)", ""]
            names = [n.strip() for n in field(body, "Mechanisms:").split(",") if n.strip()]
            names = [] if [n.lower() for n in names] in ([], ["none"]) else names
            have, shown = cards(intent), []
            lower = {k.lower(): k for k in have}
            for n in names:
                key = n if n in have else lower.get(n.lower())
                shown.append(have[key] if key else f"### {n}\nnot a mechanism card in intent.md")
            out += [f"## docs/project/intent.md · Mechanism cards {mid} names",
                    "\n\n".join(shown) or "none (Mechanisms names no card)", ""]

    if decisions is None:
        out += ["## docs/project/decisions.md", "not found", ""]
    else:
        # without the "## ", so an entry's heading never reads as one of the digest's own parts
        heads = [m.group(1).strip() for m in re.finditer(r"^## (D-\d{3,}\b.*)$", clean(decisions), re.M)]
        out += [f"## docs/project/decisions.md · last {LAST_DECISIONS} entries (headings)",
                "\n".join(heads[-LAST_DECISIONS:]) or "none recorded", ""]

    full = [str(p) for p in paths.values() if p.is_file()]
    out.append(f"Full files: {', '.join(full)}. Read any of them when a detail is not above.")
    return "\n".join(out)


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    root = find_project(argv[0])
    if root is None:
        print(f"reentry_digest: no docs/project/state.md at or above {argv[0]}; nothing to re-read here")
        return 1
    print(digest(root))
    return 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
