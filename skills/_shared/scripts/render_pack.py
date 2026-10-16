#!/usr/bin/env python3
"""Render the input pack for one isolated checker, from files only.

Usage:
  render_pack.py <role> --project <dir> --out <file> [--milestone M<k>] [--pass 1|2|3]
                 [--mode demo|reverify|fidelity|extract] [--round <n>] [--copy <dir>] [--inputs <file> ...]
                 [--extra <heading>=<file> ...] [--docs <file> ...] [--with-record] [--previous <result.md>]
                 [--layer1 <layer1.json>] [--scope <scope.json>]

Roles and what their pack contains (nothing else reaches the checker):
  code-verifier    review mode: the milestone's section of milestones.md; the done examples it carries and
                   the mechanism cards it names (intent.md with re-freezes applied); the must-not-lose
                   items with a "check:" (the rest are the owner's to judge); interfaces.md; the labeled
                   commands (AGENTS.md); with --layer1, the gate's deterministic results (each check's name,
                   status, exit, and reason, and its "for_reviewer" items: what the gate could not run); the
                   stack pack; stand-in consents from decisions.md (and, in a venture project,
                   truth/position.md); the inventory candidates for --copy; the change since the milestone's
                   baseline; any --extra blocks; the structure lens (skills/craft/review/code-quality-review.md
                   and comment-keep-list.md, verbatim).
                   The change: a table of every changed file (status, added and removed lines, kind: contract
                   or wiring, code, test, manifest, lockfile, generated, vendored, binary, other) and up to
                   DIFF_BUDGET (20,000) bytes of hunks in priority order: the files the milestone's Wiring
                   table or Interfaces line names (and interfaces.md), other code, tests, the rest. Lockfiles,
                   generated, vendored, and binary files are listed, never inlined; a file that does not fit is
                   marked "not inlined: read it in the full patch". The full patch (every text file, no budget)
                   is written beside the pack: --out <dir>/<stem>.pack.md writes <dir>/<stem>.change.patch,
                   named in the pack by absolute path and listed in its manifest (run_isolated.py lets the
                   checker read it). It is never written inside --copy: a pack whose patch would land there is
                   bad usage. No baseline: NOT PROVIDED.
                   reverify mode (--scope <scope.json>, the focused re-verify regate_scope.py classifies): the
                   milestone's section; its carried done examples and named mechanism cards; the open findings
                   to re-verify with their files and fixed_when (for a hotfix, the fix-log entries' title,
                   symptom, and reproduction); the delta since the scope's earlier candidate (its delta_patch),
                   inlined and written to <stem>.change.patch as in review mode; the --layer1 results; the
                   labeled commands; the stack pack; the structure lens. Not the whole change since the
                   baseline: the last full review covered it. A missing scope, one whose "scope" is not
                   "focused", or one for another milestone exits 2.
                   demo mode: the milestone's demo ending, the labeled commands, the stack pack, and the
                   regression endings of the accepted or gate-passed milestones: all of them for the final
                   milestone (the last one not dropped); otherwise an ending replays when its
                   docs/project/reviews/M<j>.changed.txt (baseline.py changed --write, at its acceptance) is
                   missing or unreadable, when a file changed since this milestone's baseline is on that list,
                   when the change touches a dependency manifest, lockfile, migration, build or CI
                   configuration, or shared configuration (REPLAY_ALL), or when the change cannot be computed
                   (no baseline). Each ending skipped is listed with the reason.
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
from adopt import BINARY_EXT, GENERATED, LOCKFILES, TEST, VENDORED  # noqa: E402
from baseline import changes as baseline_changes, counts as diff_counts, split_hunks, split_patch  # noqa: E402
from gate_keys import commands, read_keys  # noqa: E402
from intent_lock import effective  # noqa: E402
from languages import language  # noqa: E402

DIFF_BUDGET = 20000  # bytes of hunks a review or re-verify pack inlines; the full patch sits beside the pack
LENS = HERE.parent.parent / "craft" / "review"  # skills/craft/review, in the repository and in ~/.claude/skills
LENS_FILES = ("code-quality-review.md", "comment-keep-list.md")
LOCKFILE_NAMES = LOCKFILES | {"Pipfile.lock", "Package.resolved", "gradle.lockfile", "flake.lock", "deno.lock",
                              "mix.lock", "pubspec.lock", "packages.lock.json", "npm-shrinkwrap.json"}
MANIFEST = re.compile(r"(^|/)(package\.json|pyproject\.toml|setup\.py|setup\.cfg|requirements[^/]*\.(txt|in)|"
                      r"Pipfile|Cargo\.toml|go\.mod|Gemfile|Podfile|composer\.json|build\.gradle(\.kts)?|"
                      r"settings\.gradle(\.kts)?|pom\.xml|Package\.swift|mix\.exs|deno\.jsonc?|pubspec\.yaml|"
                      r"[^/]+\.csproj|[^/]+\.gemspec)$")
TEST_FILE = re.compile(TEST.pattern + r"|Tests?\.swift$|(^|/)conftest\.py$")
NEVER_INLINED = ("lockfile", "generated", "vendored", "binary")
TIER = {"contract or wiring": 0, "code": 1, "test": 2}  # inlining order; every other inlinable kind comes after
# A change to any of these can break what every earlier milestone delivered, so in demo mode it replays every
# regression ending. Conservative on purpose: a needless replay costs minutes, a skipped one lets a regression by.
REPLAY_ALL = (
    ("dependency manifest", MANIFEST),
    ("lockfile", re.compile(r"(^|/)(" + "|".join(re.escape(n) for n in sorted(LOCKFILE_NAMES)) + r")$")),
    ("migration", re.compile(r"(^|/)(migrations?|migrate|alembic|schemas?)(/|\.)|\.sql$", re.I)),
    ("build or CI configuration", re.compile(
        r"(^|/)(Makefile|GNUmakefile|CMakeLists\.txt|Dockerfile[^/]*|[^/]*compose[^/]*\.ya?ml|Jenkinsfile|"
        r"Procfile|[Jj]ustfile|Taskfile\.ya?ml|BUILD(\.bazel)?|WORKSPACE|tox\.ini|noxfile\.py|\.gitlab-ci\.yml|"
        r"\.travis\.yml|azure-pipelines\.yml|netlify\.toml|vercel\.json|fly\.toml|tsconfig[^/]*\.json|"
        r"jsconfig\.json|[^/]*\.config\.[cm]?[jt]s|\.babelrc[^/]*|\.swcrc|project\.pbxproj|[^/]+\.xcconfig|"
        r"gradle\.properties|\.nvmrc|\.node-version|\.python-version|\.tool-versions|runtime\.txt)$|"
        r"(^|/)\.(github|circleci|buildkite)/")),
    ("shared configuration", re.compile(
        r"(^|/)(\.env[^/]*|config|conf|settings)(/|$)|(^|/)(settings|config|conf)\.[A-Za-z]+$|"
        r"(^|/)(app|application)\.(json|ya?ml|toml|properties)$|\.(ini|cfg|properties)$")),
)


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

    def raw(self, path):
        """The bytes of a file the pack draws on (listed in the manifest), or None when it cannot be read."""
        try:
            data = Path(path).read_bytes()
        except OSError:
            return None
        try:
            label = Path(path).relative_to(self.project).as_posix()
        except ValueError:
            label = str(path)
        self.sources.append((label, hashlib.sha256(data).hexdigest()))
        return data

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


# ---- the change under review: a file table, hunks within DIFF_BUDGET, the full patch beside the pack ----------
def at(project, path):
    """A path given on the command line: absolute, or relative to the project (as Pack.read reads it)."""
    return Path(path) if Path(path).is_absolute() else project / path


def patch_path(out):
    """<dir>/<stem>.change.patch for --out <dir>/<stem>.pack.md (any other name: its stem)."""
    out = Path(out).resolve()
    stem = out.name[:-len(".pack.md")] if out.name.endswith(".pack.md") else out.stem
    return out.parent / f"{stem}.change.patch"


def put_patch(pack, path, data):
    """Write the full patch (listed in the manifest), or with no data remove one an earlier render left there,
    so a stale patch is never read as this change."""
    if data is None:
        try:
            path.unlink()
        except OSError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    pack.sources.append((str(path), hashlib.sha256(data).hexdigest()))


def named_files(ms, rels):
    """The changed files the milestone's Wiring table or Interfaces line names, by path or by file name."""
    text = "\n".join(t for t in (field_block(ms, "Wiring:"), field(ms, "Interfaces:")) if t)
    named = set()
    for rel in rels:
        name = rel.rsplit("/", 1)[-1]
        if re.search(rf"(?<![\w./-]){re.escape(rel)}(?![\w/-])", text) or \
                ("." in name and re.search(rf"(?<![\w./-]){re.escape(name)}(?![\w/-])", text)):
            named.add(rel)
    return named


def kind_of(rel, named, binary=False):
    name = rel.rsplit("/", 1)[-1]
    if binary or Path(rel).suffix.lower() in BINARY_EXT:
        return "binary"
    if name in LOCKFILE_NAMES:
        return "lockfile"
    if GENERATED.search(rel):
        return "generated"
    if any(rel.startswith(v) or f"/{v}" in rel for v in VENDORED):
        return "vendored"
    if rel in named or name == "interfaces.md":
        return "contract or wiring"
    if TEST_FILE.search(rel):
        return "test"
    if MANIFEST.search(rel):
        return "manifest"
    return "code" if language(rel) else "other"


def fenced(text, lang=""):
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    bar = "`" * max(3, longest + 1)
    return f"{bar}{lang}\n{text.rstrip(chr(10))}\n{bar}"


def change_body(entries, named, patch, lead):
    """The file table and the hunks inlined within DIFF_BUDGET, in priority order. Each entry: path, status,
    added, removed, diff (None when there is no text diff), and binary."""
    for e in entries:
        e["kind"] = kind_of(e["path"], named, e.get("binary") or False)
    inlinable = [e for e in entries if e["kind"] not in NEVER_INLINED and e.get("diff")]
    # Within the first tier the code a wiring row names comes before the tests it names.
    inlinable.sort(key=lambda e: (TIER.get(e["kind"], 3), bool(TEST_FILE.search(e["path"])), e["path"]))
    left, blocks = DIFF_BUDGET, []
    for e in inlinable:
        head, hunks = split_hunks(e["diff"])
        if not hunks:
            e["note"] = "no line changes"
            continue
        taken, cost = 0, len(head.encode("utf-8"))
        for h in hunks:
            if cost + len(h.encode("utf-8")) > left:
                break
            cost += len(h.encode("utf-8"))
            taken += 1
        if not taken:
            e["note"] = "not inlined: read it in the full patch"
            continue
        left -= cost
        blocks.append(head + "".join(hunks[:taken]))
        e["note"] = "inlined" if taken == len(hunks) else \
            f"partly inlined ({taken} of {len(hunks)} hunks): read the rest in the full patch"
    for e in entries:
        if "note" not in e:
            e["note"] = f"listed only ({e['kind']})" if e["kind"] in NEVER_INLINED or e.get("binary") else \
                "no line changes" if e.get("diff") == "" else "not in the patch"
    n = {s: sum(1 for e in entries if e["status"] == s) for s in ("added", "deleted", "modified")}
    plus = sum(e["added"] for e in entries if isinstance(e.get("added"), int))
    minus = sum(e["removed"] for e in entries if isinstance(e.get("removed"), int))
    width = max(len(e["path"]) for e in entries)
    rows = []
    for e in sorted(entries, key=lambda e: e["path"]):
        nums = f"+{e['added']} -{e['removed']}" if isinstance(e.get("added"), int) else "-"
        rows.append(f"{e['status']:<10}{e['path']:<{width}}  {nums:>13}  {e['kind']:<18}  {e['note']}")
    used = DIFF_BUDGET - left
    text = [lead + f" {len(entries)} file(s) changed ({n['added']} added, {n['deleted']} deleted, "
                   f"{n['modified']} modified), +{plus} -{minus} lines.",
            "",
            f"The full patch: {patch}. Read it with the Read tool; it is outside the copy under review.",
            "",
            f"Inlined below: {used} of at most {DIFF_BUDGET} bytes of hunks, in this order: the files the "
            "milestone's Wiring table or Interfaces line names, other code, tests, the rest. Lockfiles, generated, "
            "vendored, and binary files are listed, never inlined. A file not inlined or partly inlined is read "
            "in the full patch.",
            "",
            "Files (status, path, lines added and removed, kind, inlined):",
            fenced("\n".join(rows))]
    if blocks:
        text += ["", fenced("\n".join(b.rstrip("\n") for b in blocks), "diff")]
    return "\n".join(text)


def binary_line(f):
    a = "/dev/null" if f["status"] == "added" else f"a/{f['path']}"
    b = "/dev/null" if f["status"] == "deleted" else f"b/{f['path']}"
    return f"Binary files {a} and {b} differ\n"


def review_change(pack, project, mid, ms, patch):
    """The change since the milestone's baseline: listed, partly inlined, and written in full beside the pack."""
    heading = "Change since the milestone started"
    ch = baseline_changes(project, mid)
    if ch is None:
        put_patch(pack, patch, None)
        pack.need(heading, None, f".evidence/baseline-{mid}.txt (baseline.py record at the milestone start)")
        return
    pack.read(f".evidence/baseline-{mid}.txt")
    files = ch["files"]
    if not files:
        put_patch(pack, patch, None)
        pack.add(heading, f"Baseline {ch['from']} (the {mid} start) -> now {ch['to']}: no product file changed.")
        return
    put_patch(pack, patch, "".join(f["diff"] if f["diff"] is not None else binary_line(f)
                                   for f in files).encode("utf-8"))
    entries = [{**f, "binary": f["diff"] is None} for f in files]
    pack.add(heading, change_body(entries, named_files(ms, [f["path"] for f in files]), patch,
                                  f"Baseline {ch['from']} (the {mid} start) -> now {ch['to']}:"))


def delta_change(pack, project, scope, ms, patch):
    """A focused re-verify's delta: the scope's changed files and its delta patch, as review_change lays it out."""
    since = scope.get("since") if isinstance(scope.get("since"), dict) else {}
    heading = f"Change since round {since.get('round', '?')}'s candidate"
    src = scope.get("delta_patch")
    data = pack.raw(at(project, src)) if isinstance(src, str) and src else None
    if data is None:
        put_patch(pack, patch, None)
        pack.need(heading, None, f"the delta patch {src or '(scope.json names none)'} (scope.json delta_patch)")
        return
    put_patch(pack, patch, data)
    listed = [f for f in scope.get("changed_files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str)]
    blocks = split_patch(data.decode("utf-8", errors="replace"), {f["path"] for f in listed})
    entries = []
    for f in listed + [{"path": p} for p in sorted(set(blocks) - {f["path"] for f in listed})]:
        b = blocks.get(f["path"])
        diff = b["text"] if b and not b["binary"] else None
        a, r = f.get("added"), f.get("removed")
        if not (isinstance(a, int) and isinstance(r, int)):
            a, r = diff_counts(diff) if diff is not None else (None, None)
        entries.append({"path": f["path"], "status": f.get("status") or (b["status"] if b else "modified"),
                        "added": a, "removed": r, "diff": diff, "binary": bool(b and b["binary"])})
    lead = (f"The delta from round {since.get('round', '?')}'s candidate ({since.get('fingerprint', '?')}) to this "
            "one. The whole change since the milestone baseline was covered by the last full review and is not "
            "repeated here.")
    if not entries:
        pack.add(heading, lead + " The delta patch holds no file.")
        return
    pack.add(heading, change_body(entries, named_files(ms, [e["path"] for e in entries]), patch, lead))


# ---- what the gate already ran, the structure lens, the scope of a focused round -----------------------------
def layer1_body(pack, path):
    """The gate's deterministic results, compact; None when the file is missing or not layer1.json's shape."""
    data = pack.raw(path)
    try:
        doc = json.loads(data.decode("utf-8")) if data is not None else None
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get("checks"), list):
        return None
    lines = [f"Overall: {doc.get('status', 'not stated')}", ""]
    for c in doc["checks"]:
        if isinstance(c, dict):
            lines.append(f"- {c.get('name', '?')}: {c.get('status', '?')}, exit {c.get('exit', '?')}" +
                         (f" ({c['reason']})" if c.get("reason") else ""))
    todo = doc.get("for_reviewer")
    if isinstance(todo, list) and todo:
        lines += ["", "### Not run by the gate: check these yourself", ""]
        for t in todo:
            if isinstance(t, dict):
                lines.append(f"- {t.get('milestone', '?')} {t.get('id', '?')}: {t.get('what', '')}" +
                             (f" (why the gate did not run it: {t['why']})" if t.get("why") else ""))
            else:
                lines.append(f"- {t}")
    return "\n".join(lines)


def add_layer1(pack, project, opts):
    if opts.get("layer1"):
        pack.need("Deterministic layer (already run by the gate; do not run these again)",
                  layer1_body(pack, at(project, opts["layer1"])),
                  f"{opts['layer1']} (the gate's deterministic layer results)")


def add_lens(pack):
    texts = [(name, pack.read(str(LENS / name))) for name in LENS_FILES]
    absent = [str(LENS / name) for name, text in texts if not (text and text.strip())]
    pack.need("Structure lens (finding class structure)",
              None if absent else "\n\n".join(f"### {name}\n\n{demote(text.strip())}" for name, text in texts),
              "the structure lens " + ", ".join(absent))


def load_scope(project, opts, mid):
    """(scope.json of a focused re-verify, None) or (None, why it cannot be used)."""
    path = opts.get("scope")
    if not path:
        return None, "reverify mode needs --scope <scope.json> (regate_scope.py writes it)"
    try:
        scope = json.loads(at(project, path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"cannot read the scope {path}: {exc}"
    if not isinstance(scope, dict) or scope.get("scope") != "focused":
        got = scope.get("scope") if isinstance(scope, dict) else None
        return None, (f"the scope {path} says {got!r}, not 'focused': a full round renders the review pack "
                      "(no --mode reverify)")
    if mid and scope.get("milestone") and scope["milestone"] != mid:
        return None, f"the scope {path} is for {scope['milestone']}, not {mid}"
    return scope, None


def to_reverify(scope):
    """(heading, body, what is missing) for the findings or, for a hotfix, the fix-log entries to re-verify.
    A fix entry's Change line (the builder's account of how the fix works) stays out: the delta shows it (D8)."""
    if scope.get("kind") == "hotfix":
        rows = []
        for f in scope.get("fixes") or []:
            if isinstance(f, dict):
                rows.append(f"- {f.get('id', '?')} {f.get('title', '')}".rstrip() +
                            "".join(f"\n  {k}: {f[k]}" for k in ("symptom", "reproduction") if f.get(k)))
        return "The fix to re-verify (fix-log entries)", "\n".join(rows) or None, "the fix-log entries (scope.json fixes)"
    rows = []
    for f in scope.get("findings") or []:
        if isinstance(f, dict):
            tags = ", ".join(str(f[k]) for k in ("class", "severity") if f.get(k))
            files = f.get("files") if isinstance(f.get("files"), list) else []
            rows.append(f"- {f.get('id', '?')}" + (f" [{tags}]" if tags else "") + f" {f.get('summary', '')}".rstrip() +
                        (f"\n  where: {f['where']}" if f.get("where") else "") +
                        f"\n  files: {', '.join(map(str, files)) or 'none named'}" +
                        f"\n  fixed when: {f.get('fixed_when') or 'not stated'}")
    return "Open findings to re-verify", "\n".join(rows) or None, "the open findings (scope.json findings)"


def changed_list(pack, path):
    """The paths in a reviews/M<j>.changed.txt, or None when it is missing or unreadable."""
    data = pack.raw(path)
    try:
        text = data.decode("utf-8") if data is not None else None
    except UnicodeDecodeError:
        text = None
    return None if text is None else {ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")}


def regression_scope(pack, project, ms_text, mid):
    """([(M<j>, its section, why it replays)], [(M<j>, why it does not)]) over the other accepted or
    gate-passed milestones (in a campaign, gate-passed ones await batched acceptance)."""
    others = [(m, t) for m, t in all_milestones(ms_text)
              if m != mid and (re.search(r"^Status:\s*accepted", t, flags=re.M) or "gate-passed [x]" in t)]
    if not others:
        return [], []
    if not mid or is_final(ms_text, mid):
        return [(m, t, "this is the final milestone, which replays every earlier ending") for m, t in others], []
    ch = baseline_changes(project, mid)
    if ch is None:
        why = f"the change since the {mid} baseline cannot be computed (no .evidence/baseline-{mid}.txt)"
        return [(m, t, why) for m, t in others], []
    pack.read(f".evidence/baseline-{mid}.txt")
    now = sorted(f["path"] for f in ch["files"])
    broad = [(rel, label) for rel in now for label, rx in REPLAY_ALL if rx.search(rel)]
    if broad:
        rel, label = broad[0]
        more = len({r for r, _ in broad}) - 1
        why = (f"the change touches {rel} ({label})" + (f" and {more} more such file(s)" if more else "") +
               ", which can affect every milestone")
        return [(m, t, why) for m, t in others], []
    keep, skip = [], []
    for m, t in others:
        rel = f"docs/project/reviews/{m}.changed.txt"
        listed = changed_list(pack, project / rel)
        if listed is None:
            keep.append((m, t, f"its list of changed files ({rel}) is missing or unreadable"))
            continue
        hit = sorted(listed & set(now))
        if hit:
            keep.append((m, t, ", ".join(hit[:5]) + (f" and {len(hit) - 5} more" if len(hit) > 5 else "") +
                         f" changed since the {mid} baseline and {'is' if len(hit) == 1 else 'are'} among its "
                         f"{len(listed)} changed files"))
        else:
            skip.append((m, f"none of its {len(listed)} changed files changed since the {mid} baseline"))
    return keep, skip


def render(role, opts):
    project = Path(opts["project"]).resolve()
    pack = Pack(project)
    mid = opts.get("milestone")
    mode = opts.get("mode")
    scope = patch = None
    if role == "code-verifier" and mode != "demo":
        patch = patch_path(opts["out"])
        copy = Path(opts["copy"]).resolve() if opts.get("copy") else None
        if copy and (patch == copy or copy in patch.parents):
            print(f"render_pack: the full patch would land at {patch}, inside the copy under review ({copy}); "
                  "write the pack (--out) outside --copy", file=sys.stderr)
            return 2, None
        if mode == "reverify":
            scope, why = load_scope(project, opts, mid)
            if scope is None:
                print(f"render_pack: {why}", file=sys.stderr)
                return 2, None
            mid = mid or scope.get("milestone")
            pack.raw(at(project, opts["scope"]))
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
        keep, skip = regression_scope(pack, project, ms_text or "", mid)
        pack.add("Regression demo endings (accepted or gate-passed milestones)",
                 "\n\n".join(f"### {m}\n(replayed: {why})\n{field_block(t, 'Demo ending:') or '(no demo ending)'}"
                             for m, t, why in keep) or ("none replayed (see below)" if skip else "none"))
        pack.add("Regression demo endings not replayed",
                 "\n".join(f"- {m}: not replayed: {why}" for m, why in skip) or None)
        pack.need("Commands", labeled_commands(project), "AGENTS.md Commands section (labeled lines)")
        pack.add("Stack pack", stack_pack(project))
        title = f"Demo pack: {mid}"
    elif role == "code-verifier" and mode == "reverify":
        pack.need("Milestone contract", ms, f"the {mid} section of docs/project/milestones.md")
        have = bool(ms and intent)
        pack.need("Product-level done examples this milestone carries", carried(eff, ms) if have else None,
                  "the carried I-D examples (docs/project/intent.md)")
        pack.need("Mechanism cards this milestone exercises", named_cards(intent, ms) if have else None,
                  "the mechanism cards (docs/project/intent.md)")
        pack.need(*to_reverify(scope))
        delta_change(pack, project, scope, ms, patch)
        add_layer1(pack, project, opts)
        pack.need("Commands", labeled_commands(project), "AGENTS.md Commands section (labeled lines)")
        pack.add("Stack pack", stack_pack(project))
        add_lens(pack)
        since = scope.get("since") if isinstance(scope.get("since"), dict) else {}
        title = f"Re-verify pack: {mid} (focused, since round {since.get('round', '?')})"
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
        add_layer1(pack, project, opts)
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
            review_change(pack, project, mid, ms, patch)
        for heading, path in opts.get("extra", []):
            pack.need(heading, pack.read(path), path)
        add_lens(pack)
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
        if key in ("--project", "--out", "--milestone", "--pass", "--copy", "--mode", "--round", "--scope",
                   "--layer1") and i + 1 < len(rest):
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
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
