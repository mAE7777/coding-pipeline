#!/usr/bin/env python3
"""Render the input pack for one isolated checker, from files only.

Usage:
  render_pack.py <role> --project <dir> --out <file> [--milestone M<k>] [--pass 1|2] [--mode demo|fidelity]
                 [--round <n>] [--copy <dir>] [--inputs <file> ...] [--extra <heading>=<file> ...]
                 [--docs <file> ...] [--with-record] [--previous <result.md>]

Roles and what their pack contains (nothing else reaches the checker):
  code-verifier    review mode: the milestone's section of milestones.md; the done examples it carries and
                   the mechanism cards it names (intent.md with re-freezes applied); the must-not-lose
                   items with a "check:" (the rest are the owner's to judge); interfaces.md; the labeled
                   commands (AGENTS.md); the stack pack; stand-in consents from decisions.md (and, in a
                   venture project, truth/position.md); the inventory candidates for --copy; the change since the milestone's baseline (baseline.py diff); any
                   --extra blocks.
                   demo mode: the milestone's demo ending plus the demo endings of every accepted or gate-passed
                   milestone (regression), the labeled commands, and the stack pack.
  loyal-evaluator  pass 1: the "Persona (blind)" line and the labeled commands; pass 2: the Goal only; pass 3
                   (intent checks, after the blind passes): every done example, the milestone's done examples,
                   every must-not-lose item, and each mechanism card's probe, to confirm one by one.
  gate-judge       every --inputs file verbatim (deterministic results, checker outputs, demo evidence); the
                   intent with re-freezes applied; the milestone's section; the builder's Understanding; from
                   round 2 on, the findings ledger reviews/M<k>.findings.json.
  cold-reader      documents mode: the --docs files verbatim, the glossary of the record's own terms, with
                   --with-record the record files the documents refer to (intent, brief, milestones,
                   interfaces, decisions, AGENTS.md, the stack pack, the owner's standing requirements) as
                   context not under review, and with --previous <result.md> the earlier read, whose
                   findings a re-read settles. Understanding mode (--inputs understanding):
                   state.md's Understanding with the Goal, Must not lose, and the milestone's section.
                   Fidelity mode (--mode fidelity): the --docs transcripts verbatim, the dossier's summary
                   and only the units citing those transcripts, and with --previous the earlier read.
                   Extraction mode (--mode extract): the --docs
                   transcripts only, never the dossier.
  claim-verifier   the --inputs claims file verbatim.

The builder never writes a pack by hand: whatever the builder believes about the work is absent unless it
is in one of those files. A required input that is missing is written into the pack as NOT PROVIDED (the
checker reports what depends on it as NOT_RUN) and the exit code is 1. The pack ends with a manifest
listing every source file and its sha256.
Exit 0 on success, 1 if a required source is missing, 2 on bad usage.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gate_keys import commands, read_keys  # noqa: E402
from intent_lock import effective  # noqa: E402


def section(text, heading, level=2):
    """The body of '## heading' (or '### heading') up to the next heading of the same or higher level."""
    hashes = "#" * level
    m = re.search(rf"^{hashes} {re.escape(heading)}\s*$(.*?)(?=^#{{1,{level}}} |\Z)", text, flags=re.M | re.S)
    return m.group(1).strip() if m else None


def milestone_section(text, mid):
    m = re.search(rf"^## {re.escape(mid)} ·.*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0).strip() if m else None


def all_milestones(text):
    return [(m.group(1), m.group(0)) for m in re.finditer(r"^## (M\d+) ·.*?(?=^## |\Z)", text, flags=re.M | re.S)]


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


class Pack:
    def __init__(self, project):
        self.project = project
        self.parts, self.sources, self.missing = [], [], []

    def read(self, rel, required=False):
        p = self.project / rel if not Path(rel).is_absolute() else Path(rel)
        if not p.is_file():
            if required:
                self.missing.append(str(rel))
            return None
        data = p.read_bytes()
        self.sources.append((str(rel), hashlib.sha256(data).hexdigest()))
        return strip_comments(data.decode("utf-8", errors="replace"))

    def add(self, heading, body):
        if body is None or not str(body).strip():
            return
        self.parts.append(f"## {heading}\n\n{str(body).strip()}\n")

    def need(self, heading, body, what):
        if body is None or not str(body).strip():
            self.missing.append(what)
            self.parts.append(f"## {heading}\n\nNOT PROVIDED: {what} was not found, so the checks that "
                              "depend on it must be reported NOT_RUN, never assumed.\n")
        else:
            self.add(heading, body)

    def render(self, title):
        manifest = "\n".join(f"- {rel} · sha256 {h}" for rel, h in self.sources) or "- (none)"
        missing = "\n".join(f"- {m}" for m in self.missing) or "- none"
        return f"# {title}\n\n" + "\n".join(self.parts) + f"\n## Pack manifest\n\n{manifest}\n\nMissing inputs:\n{missing}\n"


def field(ms_section, label):
    m = re.search(rf"^{re.escape(label)}\s*(.*)$", ms_section or "", flags=re.M)
    return m.group(1).strip() if m else ""


def carried(eff, ms_section):
    ids = re.findall(r"\bI-D\d+[a-z]?\b", field(ms_section, "Carries:"))
    lines = [f"- {i} {eff['done_examples'][i]}" for i in ids if i in eff["done_examples"]]
    unknown = [i for i in ids if i not in eff["done_examples"]]
    if unknown:
        lines.append(f"(carried but not in the intent: {', '.join(unknown)})")
    return "\n".join(lines) or None


def named_cards(intent_text, ms_section):
    names = [n.strip() for n in field(ms_section, "Mechanisms:").split(",") if n.strip() and n.strip().lower() != "none"]
    body = section(intent_text, "Mechanism cards") or ""
    cards = []
    for name in names:
        m = re.search(rf"^### {re.escape(name)}\s*$(.*?)(?=^### |\Z)", body, flags=re.M | re.S)
        cards.append(f"### {name}\n{m.group(1).strip()}" if m else f"### {name}\n(NOT FOUND in intent.md)")
    return "\n\n".join(cards) if names else "none named for this milestone"


def checkable(eff):
    rows = [f"- {k} {v}" for k, v in eff["must_not_lose"].items() if "· check:" in v]
    return "\n".join(rows) or "none marked checkable"


def labeled_commands(project):
    cmds = commands(project)
    return "\n".join(f"{k}: {v}" for k, v in cmds.items()) or None


INTENT_ONLY = (
    "An intent check, not a milestone gate: the standalone check during a build, or the characterization of a "
    "project as found during adoption. By design it has no deterministic layer, no reviewer results, no demo run, "
    "and possibly no builder's Understanding; their absence is not a gap and is not reported as not run. Judge "
    "the intent diff from the evaluator's passes: the two blind passes for what the product does unasked (EXTRA, "
    "ORPHAN) and what it seems to be for, and pass 3, which confirmed every named item directly, for a row on "
    "every done example, must-not-lose item, and mechanism card. The verdict follows from those rows: ACCEPT-READY when every row "
    "holds or is an EXTRA or ORPHAN you logged, CHANGES when a row is DRIFT, MISSING, or INACCURATE, BLOCKED when "
    "only the owner can settle what you found (mark it needs_owner), and INCONCLUSIVE only when the evaluator's "
    "own output cannot ground the rows.")


def reference(name):
    for base in (Path.home() / ".claude/skills/_shared/references", HERE.parent / "references"):
        if (base / name).is_file():
            return base / name
    return None


def stack_file(project):
    name = read_keys(project).get("Stack pack")
    return reference(f"stacks/{name}.md") if name else None


def demote(text):
    """Headings of an embedded file sit below the pack's own (## section, ### file)."""
    return re.sub(r"^(#{1,6}) ", lambda m: "#" * min(6, len(m.group(1)) + 3) + " ", text, flags=re.M)


RECORD = ("docs/project/intent.md", "docs/project/brief.md", "docs/project/milestones.md",
          "docs/project/interfaces.md", "docs/project/decisions.md", "AGENTS.md")


def stack_pack(project):
    name = read_keys(project).get("Stack pack")
    if not name:
        return "none"
    for base in (Path.home() / ".claude/skills/_shared/references/stacks", HERE.parent / "references/stacks"):
        p = base / f"{name}.md"
        if p.is_file():
            return f"{name} (read {p})"
    return f"{name} (NOT FOUND in the stack packs)"


def render(role, opts):
    project = Path(opts["project"]).resolve()
    pack = Pack(project)
    mid = opts.get("milestone")
    mode = opts.get("mode")
    understanding = role == "cold-reader" and "understanding" in opts.get("inputs", [])
    needs_intent = role in ("code-verifier", "loyal-evaluator", "gate-judge") or understanding
    intent = pack.read("docs/project/intent.md", required=needs_intent) if needs_intent else None
    eff = effective(intent) if intent else {"done_examples": {}, "must_not_lose": {}, "mechanisms": [],
                                            "goal": "", "persona_blind": None}
    needs_ms = role in ("code-verifier", "gate-judge") or understanding or \
        (role == "loyal-evaluator" and opts.get("pass") == "3")
    ms_text = pack.read("docs/project/milestones.md", required=needs_ms) if needs_ms else None
    ms = milestone_section(ms_text, mid) if (ms_text and mid) else None
    agents_needed = role in ("code-verifier", "loyal-evaluator")
    if agents_needed:
        pack.read("AGENTS.md", required=True)

    if role == "code-verifier" and mode == "demo":
        pack.need("Demo ending under test", field_block(ms, "Demo ending:"), f"the {mid} demo ending")
        regressions = []
        for other, text in all_milestones(ms_text or ""):
            # Accepted milestones, and in a campaign the ones that passed their gate but await batched acceptance.
            if other != mid and (re.search(r"^Status:\s*accepted", text, flags=re.M) or "gate-passed [x]" in text):
                regressions.append(f"### {other}\n{field_block(text, 'Demo ending:')}")
        pack.add("Regression demo endings (accepted or gate-passed milestones)", "\n\n".join(regressions) or "none")
        pack.need("Commands", labeled_commands(project), "AGENTS.md Commands section (labeled lines)")
        pack.add("Stack pack", stack_pack(project))
        title = f"Demo pack: {mid}"
    elif role == "code-verifier":
        pack.need("Milestone contract", ms, f"the {mid} section of docs/project/milestones.md")
        have = bool(ms and intent)
        pack.need("Product-level done examples this milestone carries", carried(eff, ms) if have else None,
                  "the carried I-D examples (docs/project/intent.md)")
        pack.need("Mechanism cards this milestone exercises", named_cards(intent, ms) if have else None,
                  "the mechanism cards (docs/project/intent.md)")
        pack.need("Must-not-lose items with a check", checkable(eff) if intent else None,
                  "the must-not-lose items (docs/project/intent.md)")
        pack.add("Interfaces", pack.read("docs/project/interfaces.md"))
        pack.need("Commands", labeled_commands(project), "AGENTS.md Commands section (labeled lines)")
        pack.add("Stack pack", stack_pack(project))
        consents = []
        for rel in ("docs/project/decisions.md", "truth/position.md"):
            text = pack.read(rel)
            consents += [f"{rel}: {line.strip()}" for line in
                         re.findall(r"^.*\[placeholder-consent:[^\]]*\].*$", text or "", flags=re.M)]
        pack.add("Stand-in consents on record", "\n".join(consents) or "none on record")
        if opts.get("copy"):
            inv = subprocess.run([sys.executable, str(HERE / "inventory.py"), opts["copy"]],
                                 capture_output=True, text=True).stdout
            pack.add("Inventory: silent-degradation candidates, routes, and model calls (adjudicate each)", inv)
        if mid:
            r = subprocess.run([sys.executable, str(HERE / "baseline.py"), "diff", str(project), mid],
                               capture_output=True, text=True)
            pack.need("Change since the milestone started", r.stdout if r.returncode == 0 else None,
                      f".evidence/baseline-{mid}.txt (baseline.py record at the milestone start)")
        for heading, path in opts.get("extra", []):
            pack.need(heading, pack.read(path), path)
        if mid and is_final(ms_text or "", mid):
            tables = "\n\n".join(f"### {other}\n{field_block(text, 'Wiring:') or '(no wiring table)'}"
                                  for other, text in all_milestones(ms_text or "")
                                  if not re.search(r"^Status:\s*dropped", text, flags=re.M))
            pack.add("Whole-product checks (this is the final milestone)",
                     "Also check the whole product: every milestone's wiring rows below against the code's routes, "
                     "events, and model calls; terms used consistently across the documents and the product; "
                     "entities in interfaces that no intent example uses; docs and changelog current; "
                     "accessibility and performance where they apply; and nothing load-bearing shipped as a "
                     "simplified stand-in of its mechanism without a live consent (report that as "
                     "`simplified-stand-in`).\n\n" + tables)
        title = f"Review pack: {mid}"
    elif role == "loyal-evaluator":
        if opts.get("pass", "1") == "1":
            pack.need("Who uses this", eff.get("persona_blind"), "intent.md 'Persona (blind):' line")
            pack.need("Commands", labeled_commands(project), "AGENTS.md Commands section (labeled lines)")
            title = "Reconstruction pack, pass 1"
        elif opts.get("pass") == "3":
            items = [f"- {k} {v}" for k, v in eff["done_examples"].items()]
            items += re.findall(rf"^- ({re.escape(mid)}\.D\d+[a-z]? .*)$", ms or "", flags=re.M) if mid else []
            items += [f"- {k} {v}" for k, v in eff["must_not_lose"].items()]
            cards = section(intent or "", "Mechanism cards") or ""
            for name, body in re.findall(r"^### (.+?)\s*$(.*?)(?=^### |\Z)", cards, flags=re.M | re.S):
                probe = re.search(r"^Discriminating probe:\s*(.+)$", body, flags=re.M)
                items.append(f"- MECH-{name.strip()}: {probe.group(1).strip() if probe else '(no probe written)'}")
            pack.need("What to confirm, item by item", "\n".join(items) or None,
                      "done examples, must-not-lose items, and mechanism cards (docs/project/intent.md)")
            pack.need("Commands", labeled_commands(project), "AGENTS.md Commands section (labeled lines)")
            title = "Reconstruction pack, pass 3 (directed confirmation)"
        else:
            pack.need("The one-line goal", eff.get("goal"), "intent.md Goal")
            title = "Reconstruction pack, pass 2"
    elif role == "gate-judge":
        if opts.get("intent_only"):
            pack.add("What this check is", INTENT_ONLY)
        for f in opts.get("inputs", []):
            pack.need(f"Input: {Path(f).name}", pack.read(f), f)
        pack.need("Intent (re-freezes applied)", json.dumps({k: eff[k] for k in ("goal", "done_examples",
                                                                                "must_not_lose", "mechanisms")},
                                                           indent=2, ensure_ascii=False) if intent else None,
                  "docs/project/intent.md")
        pack.need("Mechanism cards", section(intent or "", "Mechanism cards"), "intent.md Mechanism cards")
        pack.need("Milestone contract", ms, f"the {mid} section of docs/project/milestones.md")
        state = pack.read("docs/project/state.md")
        if opts.get("intent_only"):
            pack.add("The builder's Understanding", section(state or "", "Understanding"))
        else:
            pack.need("The builder's Understanding", section(state or "", "Understanding"), "state.md Understanding")
        if opts.get("intent_only"):
            # A standalone intent check has no gate ledger of its own; an existing gate ledger is context only.
            pack.add("Findings ledger (gate rounds)", pack.read(f"docs/project/reviews/{mid}.findings.json"))
        elif int(opts.get("round", "1")) > 1:
            pack.need("Findings ledger (earlier rounds)", pack.read(f"docs/project/reviews/{mid}.findings.json"),
                      f"docs/project/reviews/{mid}.findings.json")
        title = f"Judgment pack: {mid}" + (" (intent check)" if opts.get("intent_only") else "")
    elif role == "cold-reader":
        if understanding:
            state = pack.read("docs/project/state.md", required=True)
            pack.need("The builder's restatement", section(state or "", "Understanding"), "state.md Understanding")
            pack.need("Goal", eff.get("goal"), "intent.md Goal")
            pack.need("Must not lose", "\n".join(f"- {k} {v}" for k, v in eff["must_not_lose"].items()),
                      "intent.md Must not lose")
            pack.need("Milestone contract", ms, f"the {mid} section of milestones.md")
            title = "Cold read, understanding mode"
        elif mode == "fidelity":
            srcs = set()
            for f in opts.get("docs", []):
                pack.need(f"Transcript: {f}", pack.read(f), f)
                srcs.update(re.findall(r"\b(SRC-\d+)-", f))
            dossier = pack.read("docs/project/sources/dossier.md")
            # Only the units that cite these sources (and the summary): the audit is about these transcripts, and a
            # whole dossier per audit is paid for again in every portion.
            pack.need("Dossier (the summary and the units citing these transcripts)",
                      cited_units(dossier, srcs) if dossier and srcs else dossier, "docs/project/sources/dossier.md")
            if opts.get("previous"):
                pack.need("Previous read (say for each of its material items whether it is now settled)",
                          pack.read(opts["previous"]), opts["previous"])
            title = "Cold read, fidelity mode"
        elif mode == "extract":
            # The sources only: an extraction that saw the dossier would confirm it instead of finding what it lacks.
            for f in opts.get("docs", []):
                pack.need(f"Document: {f}", pack.read(f), f)
            title = "Cold read, extraction mode"
        else:
            docs = opts.get("docs", [])
            for f in docs:
                pack.need(f"Document: {f}", pack.read(f), f)
            if opts.get("previous"):
                pack.need("Previous read (settle its material findings; see your instructions)",
                          pack.read(opts["previous"]), opts["previous"])
            if opts.get("with_record"):
                reviewed = {(project / d).resolve() if not Path(d).is_absolute() else Path(d).resolve() for d in docs}
                context = [(rel, pack.read(rel)) for rel in RECORD if (project / rel).resolve() not in reviewed]
                for label, path in (("stack pack", stack_file(project)),
                                    ("owner's standing requirements", reference("owner-standing.md"))):
                    if path:
                        context.append((f"{label} ({path.name})", pack.read(str(path))))
                pack.add("Context: files the documents refer to (use them to resolve references; not under review)",
                         "\n\n".join(f"### {rel}\n\n{demote(text.strip())}" for rel, text in context if text))
            glossary = reference("record-glossary.md")
            pack.add("Glossary of the record's own terms", pack.read(str(glossary)) if glossary else None)
            title = "Cold read, documents mode"
    elif role == "claim-verifier":
        for f in opts.get("inputs", []):
            pack.need("Claims to verify", pack.read(f), f)
        title = "Claims pack"
    else:
        print(f"render_pack: unknown role {role}", file=sys.stderr)
        return 2, None
    return (1 if pack.missing else 0), pack.render(title)


def is_final(ms_text, mid):
    """True when no milestone after mid is still to be built (every later one is dropped)."""
    ids = [m for m, _ in all_milestones(ms_text)]
    if mid not in ids:
        return False
    later = [text for m, text in all_milestones(ms_text)[ids.index(mid) + 1:]]
    return all(re.search(r"^Status:\s*dropped", t, flags=re.M) for t in later)


def field_block(ms_section, label):
    """Lines after 'Label:' up to the next 'Word:' label line."""
    if not ms_section:
        return None
    out, inside = [], False
    for line in ms_section.splitlines():
        if line.startswith(label):
            inside = True
            continue
        if inside:
            if re.match(r"^[A-Z][A-Za-z -]+:( |$)", line):
                break
            if line.strip():
                out.append(line)
    return "\n".join(out) or None


def cited_units(dossier, srcs):
    """The dossier's summary and the units whose references name any of the sources."""
    where = re.search(r"^## Where it stands\s*$(.*?)(?=^## )", dossier, re.M | re.S)
    units = re.search(r"^## Units\s*$(.*?)(?=^## |\Z)", dossier, re.M | re.S)
    blocks = re.split(r"(?m)^(?=- S-\d+ · )", units.group(1)) if units else []
    keep = [b.rstrip() for b in blocks if b.startswith("- S-")
            and set(re.findall(r"\b(SRC-\d+)\b", b.splitlines()[0])) & srcs]
    return "\n".join(["## Where it stands", (where.group(1).strip() if where else "(none)"), "", "## Units",
                      *(keep or ["(no unit cites these transcripts)"])])


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    role, rest = argv[0], argv[1:]
    opts = {"inputs": [], "docs": [], "extra": []}
    i = 0
    while i < len(rest):
        key = rest[i]
        if key in ("--project", "--out", "--milestone", "--pass", "--copy", "--mode", "--round") and i + 1 < len(rest):
            opts[key[2:]] = rest[i + 1]
            i += 2
        elif key in ("--inputs", "--docs") and i + 1 < len(rest):
            opts[key[2:]].append(rest[i + 1])
            i += 2
        elif key == "--extra" and i + 1 < len(rest) and "=" in rest[i + 1]:
            opts["extra"].append(tuple(rest[i + 1].split("=", 1)))
            i += 2
        elif key == "--intent-only":
            opts["intent_only"] = True
            i += 1
        elif key == "--with-record":
            opts["with_record"] = True
            i += 1
        elif key == "--previous" and i + 1 < len(rest):
            opts["previous"] = rest[i + 1]
            i += 2
        else:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    if "project" not in opts or "out" not in opts:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    code, text = render(role, opts)
    if text is None:
        return code
    Path(opts["out"]).parent.mkdir(parents=True, exist_ok=True)
    Path(opts["out"]).write_text(text, encoding="utf-8")
    print(opts["out"])
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
