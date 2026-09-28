#!/usr/bin/env python3
"""Turn one gate round's evidence into the verdict, the review record, and the findings ledger.

Usage:
  gate_report.py <project> --milestone M<k> --round <n> --evidence <dir> --fingerprint <fp> [--intent-only]

Reads from <dir>: layer1.json (the deterministic layer), copies.json (the copies manifest), the checker
summaries (<role>[-demo][-pass2].summary.json) and results, and gate-judge.result.md, whose last fenced JSON
block is the judge's verdict. Writes <dir>/verdict.json, appends a round block to
docs/project/reviews/M<k>.md, updates docs/project/reviews/M<k>.findings.json, and moves the milestone's
status (CHANGES sets "changes"; ACCEPT-READY ticks "gate-passed (<fingerprint>)" in its Readiness line, replacing an
older tick; any other verdict clears it).

The verdict is computed, never taken on trust, from the judge's JSON and from the checkers' own results:
  1. a FAIL in the copies or the deterministic layer                              -> CHANGES
  2. a checker BLOCKED (for example a project server running)                     -> BLOCKED
  3. a checker LEAK, or ERROR / INCONCLUSIVE after its re-run, no valid JSON from the judge, the
     code-verifier (review), or the demo run, JSON of the wrong shape, or (full rounds) no copies manifest
     or deterministic-layer result                                                 -> INCONCLUSIVE
  4. a blocking finding the judge marks needs_owner, or one that has now blocked in
     two rounds (the fix loop's limit)                                             -> BLOCKED
  5. any blocking finding, an intent-diff row DRIFT, MISSING, or INACCURATE, a demo step that FAILS, a
     wiring row UNWIRED, UNCONSUMED, or PHANTOM, or a purpose guess the judge calls a different product
                                                                                   -> CHANGES
  6. an intent-diff row missing for a carried done example, a milestone done example, a must-not-lose item,
     or a mechanism card the milestone names (MECH-<card>), or a row whose status is not HOLDS, DRIFT,
     MISSING, INACCURATE, EXTRA, or ORPHAN; a judge HOLDS (or no row) where the code-verifier reported FAILS; a
     code-verifier finding of a blocking class at any severity but low that the judge neither blocks nor
     logs; a code-verifier FAIL that names nothing to triage; a demo step left UNGROUNDED, or no demo step
     for this milestone                                                            -> INCONCLUSIVE
  (Statuses, classes, and severities are compared without regard to case.)
  7. otherwise                                                                     -> ACCEPT-READY
Deterministic checks that were skipped or not run are listed as exceptions.
When the judge's own verdict is stricter than the computed one it is recorded as an exception and the
result is INCONCLUSIVE (its verdict does not follow from its findings); when it is looser, the computed
verdict stands and the disagreement is listed.
Prints the verdict JSON, and for ACCEPT-READY the evidence line, built from what each checker said:
  gate M<k> ACCEPT-READY=SHIP · code-verifier SHIP · loyal-evaluator SHIP · gate-judge SHIP · gate.sh 0-FAIL
(the code-verifier part reads "code-verifier FAIL (overruled: ...)" when its FAIL was triaged as logged, and the
gate.sh part names its status when it did not pass).
--intent-only (the standalone intent check): only the loyal-evaluator passes and the judge are required, the
copies and deterministic layer are not, the two-round rule does not apply, the milestone's status is not
changed, and the round is logged as one line in docs/project/reviews/intent-ledger.md instead of the review file.
Exit 0 when a verdict was written (whatever it is), 1 when the evidence folder is unusable, 2 on bad usage.
"""
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intent_lock import effective  # noqa: E402

STRICT = {"ACCEPT-READY": 0, "CHANGES": 1, "BLOCKED": 2}
INTENT_DEFECTS = {"DRIFT", "MISSING", "INACCURATE"}
# EXTRA (behavior nothing asked for) and ORPHAN (unexplained behavior) are findings for the judge to block or log,
# not defects by themselves, and never cover a carried item.
INTENT_NOTES = {"EXTRA", "ORPHAN"}
CHECKERS = ("code-verifier", "loyal-evaluator", "loyal-evaluator-pass2", "code-verifier-demo", "gate-judge")


def last_json(text):
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text or "", flags=re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except ValueError:
            continue
    return None


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def milestone_block(text, mid):
    m = re.search(rf"^## {re.escape(mid)} ·.*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def carried_ids(project, mid):
    """Every row the judge owes: carried I-D examples, the milestone's own done examples, every must-not-lose
    item, and MECH-<card> for each mechanism card the milestone names."""
    ms = (project / "docs/project/milestones.md")
    intent = (project / "docs/project/intent.md")
    block = milestone_block(ms.read_text(encoding="utf-8"), mid) if ms.is_file() else ""
    carries = re.search(r"^Carries:\s*(.*)$", block, flags=re.M)
    ids = re.findall(r"\bI-D\d+[a-z]?\b", carries.group(1)) if carries else []
    ids += sorted(set(re.findall(rf"^- ({re.escape(mid)}\.D\d+[a-z]?)\b", block, flags=re.M)))
    mech = re.search(r"^Mechanisms:\s*(.*)$", block, flags=re.M)
    if mech and mech.group(1).strip().lower() not in ("", "none") and not mech.group(1).startswith("<"):
        ids += [f"MECH-{n.strip()}" for n in mech.group(1).split(",") if n.strip()]
    eff = effective(intent.read_text(encoding="utf-8")) if intent.is_file() else {"must_not_lose": {}}
    return ids + list(eff["must_not_lose"])


INTENT_CHECKERS = ("loyal-evaluator", "loyal-evaluator-pass2", "gate-judge")
REVIEW_BLOCKING = {"correctness", "requirement", "security", "wiring", "silent-degradation", "quality-substitution",
                   "placeholder-unconsented", "interface"}
BROKEN_WIRING = {"UNWIRED", "UNCONSUMED", "PHANTOM"}


def checker_json(ev, name):
    p = ev / f"{name}.result.md"
    return last_json(p.read_text(encoding="utf-8")) if p.is_file() else None


def key(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def mentioned(finding, entries):
    """True when a judge entry names the reviewer finding by id, or quotes the start of its summary."""
    fid, head = key(finding.get("id")), key(finding.get("summary"))[:40]
    for e in entries:
        text = key(" ".join(str(e.get(k, "")) for k in ("id", "summary", "evidence")))
        if (fid and re.search(rf"(?<![\w-]){re.escape(fid)}(?![\w-])", text)) or (len(head) >= 20 and head in text):
            return True
    return False


def st(row):
    """A row's status, upper-cased (checkers write HOLDS, Holds, holds)."""
    return str(row.get("status") or "").strip().upper()


def cls(value):
    return key(value).replace("_", "-").replace(" ", "-")


def checker_rules(review, demo, judge, mid):
    """(forced CHANGES reasons, INCONCLUSIVE reasons) that hold whatever the judge concluded."""
    changes, unsure = [], []
    steps = demo.get("steps") or []
    for s in steps:
        where = f"demo step {s.get('milestone', '')}-{s.get('step')}"
        if st(s) == "FAILS":
            changes.append(f"{where} FAILS: expected {str(s.get('expected', ''))[:60]}, observed "
                           f"{str(s.get('observed', ''))[:60]}")
        elif st(s) != "HOLDS":
            unsure.append(f"{where} {st(s) or 'has no status'}")
    if not any(key(s.get("milestone")) == key(mid) for s in steps):
        unsure.append(f"the demo run has no step for {mid}")
    broken = []
    for w in review.get("wiring") or []:
        if st(w) in BROKEN_WIRING:
            broken.append(w)
            changes.append(f"wiring {st(w)}: {w.get('component')}")
    if (judge.get("purpose") or {}).get("same_product") is False:
        changes.append("the evaluator's purpose guess describes a different product (purpose drift)")
    rows = {key(r.get("id")): st(r) for r in judge.get("intent_diff") or []}
    failing = []
    for group, name in (("done_examples", "id"), ("must_not_lose", "id"), ("mechanisms", "name")):
        for r in review.get(group) or []:
            if st(r) != "FAILS":
                continue
            failing.append(r)
            rid = r.get(name, "")
            jid = key(f"MECH-{rid}") if group == "mechanisms" else key(rid)
            if rows.get(jid) in (None, "HOLDS"):
                unsure.append(f"the code-verifier reports {rid} FAILS but the judge's row is "
                              f"{rows.get(jid) or 'missing'}")
    triaged = (judge.get("blocking") or []) + (judge.get("logged") or [])
    findings = review.get("findings") or []
    for f in findings:
        if cls(f.get("class")) in REVIEW_BLOCKING and key(f.get("severity")) != "low" and not mentioned(f, triaged):
            unsure.append(f"code-verifier finding {f.get('id')} ({f.get('class')}, {f.get('severity')}) is neither "
                          f"blocking nor logged by the judge: {str(f.get('summary', ''))[:70]}")
    if str(review.get("verdict")).upper() == "FAIL" and not (findings or failing or broken):
        unsure.append("the code-verifier said FAIL but named no finding, failing row, or broken wiring to triage")
    return changes, unsure


def evidence_line(mid, review, layer1, judge):
    """The ACCEPT-READY line, each part saying what that checker actually reported."""
    if str((review or {}).get("verdict")).upper() == "PASS":
        cv = "code-verifier SHIP"
    else:
        logged = [e.get("id") for e in judge.get("logged") or [] if e.get("id")]
        cv = f"code-verifier {(review or {}).get('verdict', 'missing')} (overruled: {', '.join(logged) or 'no logged ids'})"
    gs = next((c.get("status") for c in layer1.get("checks", []) if c.get("name") == "gate.sh"), "NOT_RUN")
    gs = "gate.sh 0-FAIL" if gs in ("PASS", "WARN") else f"gate.sh {gs}"
    return f"gate {mid} ACCEPT-READY=SHIP · {cv} · loyal-evaluator SHIP · gate-judge SHIP · {gs}"


def compute(project, mid, rnd, ev, ledger, intent_only=False):
    reasons, exceptions = [], []
    copies = load(ev / "copies.json")
    layer1 = load(ev / "layer1.json")
    if not intent_only:
        absent = [n for n, d in (("copies.json", copies), ("layer1.json", layer1))
                  if not isinstance(d, dict) or d.get("status") not in ("PASS", "FAIL", "WARN", "NOT_RUN")]
        if absent:
            return "INCONCLUSIVE", [f"no usable {', '.join(absent)} in the evidence folder; run the round again"], \
                exceptions, None, {}
    copies = copies if isinstance(copies, dict) else {}
    layer1 = layer1 if isinstance(layer1, dict) else {}
    if copies.get("status") == "FAIL":
        reasons.append("copies: " + "; ".join(f"{k}: {len(v)}" for k, v in (copies.get("problems") or {}).items()))
    if layer1.get("status") == "FAIL":
        reasons.append("deterministic layer: " + ", ".join(c["name"] for c in layer1.get("checks", [])
                                                           if c.get("status") == "FAIL"))
    if reasons:
        return "CHANGES", reasons, exceptions, None, {}
    if layer1.get("status") == "NOT_RUN":
        return "INCONCLUSIVE", ["deterministic layer did not run: " + "; ".join(
            f"{c['name']} ({c.get('reason', '')})" for c in layer1.get("checks", []) if c.get("status") == "NOT_RUN")
            + "; run the round again"], exceptions, None, {}
    for c in layer1.get("checks", []):
        if c.get("status") in ("SKIP", "NOT_RUN"):
            exceptions.append(f"deterministic check {c.get('name')} {c.get('status')}: {str(c.get('detail', ''))[:120]}")
    required = INTENT_CHECKERS if intent_only else CHECKERS
    summaries = {c: load(ev / f"{c}.summary.json") for c in required}
    for c, s in summaries.items():
        if s is None:
            continue
        if s.get("pack_missing"):
            exceptions.append(f"{c}: inputs not provided, so the checks on them are NOT_RUN: {', '.join(s['pack_missing'])}")
        if s.get("family_switch"):
            exceptions.append(f"{c}: ran on {s['family']} because {s['family_switch']['from']} was unavailable "
                              f"({s['family_switch']['reason']})")
    for c, s in summaries.items():
        if s and s.get("status") == "BLOCKED":
            return "BLOCKED", [f"{c}: {s.get('reason')}"], exceptions, None, summaries
    for c, s in summaries.items():
        if s and s.get("status") in ("LEAK", "ERROR", "INCONCLUSIVE", "UNAVAILABLE"):
            reasons.append(f"{c}: {s['status']} {s.get('reason') or s.get('canary_hits') or ''}".strip())
    missing = [c for c in required if summaries.get(c) is None]
    if missing:
        reasons.append("did not run: " + ", ".join(missing))
    judge = last_json((ev / "gate-judge.result.md").read_text(encoding="utf-8")) \
        if (ev / "gate-judge.result.md").is_file() else None
    if judge is None or str(judge.get("verdict")).strip().upper() not in ("ACCEPT-READY", "CHANGES", "BLOCKED",
                                                                           "INCONCLUSIVE"):
        reasons.append("no valid verdict JSON from gate-judge")
    review = demo = None
    if not intent_only:
        review, demo = checker_json(ev, "code-verifier"), checker_json(ev, "code-verifier-demo")
        if review and isinstance(review.get("verdict"), str):
            review["verdict"] = review["verdict"].strip().upper()
        if not review or review.get("verdict") not in ("PASS", "FAIL", "INCONCLUSIVE"):
            reasons.append("no valid verdict JSON from the code-verifier")
        elif review.get("verdict") == "INCONCLUSIVE":
            reasons.append("the code-verifier's own verdict is INCONCLUSIVE")
        if not demo or not demo.get("steps"):
            reasons.append("no demo steps from the demo run")
    if reasons:
        return "INCONCLUSIVE", reasons, exceptions, judge, summaries
    if intent_only:
        forced = [] if (judge.get("purpose") or {}).get("same_product") is not False else \
            ["the evaluator's purpose guess describes a different product (purpose drift)"]
        unsure = []
    else:
        forced, unsure = checker_rules(review, demo, judge, mid)
    blocking = judge.get("blocking") or []
    two_rounds = [] if intent_only else \
        [b["id"] for b in blocking if b.get("id") and
         len(set(ledger.get(b["id"], {}).get("rounds_blocking", [])) - {rnd}) >= 1]
    owner = [b.get("id") or b.get("summary", "")[:40] for b in blocking if b.get("needs_owner")]
    diff = judge.get("intent_diff") or []
    defects = [r for r in diff if st(r) in INTENT_DEFECTS]
    unsure += [f"intent-diff row {r.get('id')} has status {st(r) or 'none'}" for r in diff
               if st(r) not in INTENT_DEFECTS | INTENT_NOTES | {"HOLDS"}]
    rows = {key(r.get("id")) for r in diff if st(r) in INTENT_DEFECTS | {"HOLDS"}}
    uncovered = [i for i in carried_ids(project, mid) if key(i) not in rows]
    if owner or two_rounds:
        computed = "BLOCKED"
        reasons += [f"needs the owner: {', '.join(owner)}"] if owner else []
        reasons += [f"blocked in two rounds, the owner decides: {', '.join(two_rounds)}"] if two_rounds else []
    elif blocking or defects or forced:
        computed = "CHANGES"
        reasons += [f"blocking: {b.get('id')} {b.get('summary', '')[:80]}" for b in blocking]
        reasons += [f"intent {st(r)}: {r.get('id')}" for r in defects if r.get("id") not in
                    {b.get("id") for b in blocking}]
        reasons += forced
        reasons += unsure + (["no intent-diff row for: " + ", ".join(uncovered)] if uncovered else [])
    elif uncovered or unsure:
        computed = "INCONCLUSIVE"
        reasons += (["no intent-diff row for: " + ", ".join(uncovered)] if uncovered else []) + unsure
    else:
        computed = "ACCEPT-READY"
    said = str(judge.get("verdict")).strip().upper()
    if said != computed:
        if said == "INCONCLUSIVE" or (said in STRICT and computed in STRICT and STRICT[said] > STRICT[computed]):
            exceptions.append(f"gate-judge said {said}, its findings give {computed}")
            return "INCONCLUSIVE", reasons + [f"the judge's {said} does not follow from its findings"], \
                exceptions, judge, summaries
        exceptions.append(f"gate-judge said {said}; computed {computed} from its own findings")
    for n in judge.get("not_run") or []:
        exceptions.append(f"not run: {n}")
    for n in (review or {}).get("not_run") or []:
        exceptions.append(f"code-verifier did not check: {str(n)[:160]}")
    return computed, reasons, exceptions, judge, summaries


def update_ledger(ledger, judge, rnd):
    if not judge:
        return ledger
    for b in judge.get("blocking") or []:
        fid = b.get("id")
        if not fid:
            continue
        row = ledger.setdefault(fid, {"summary": b.get("summary", ""), "first_round": rnd, "rounds_blocking": [],
                                      "status": "open"})
        if rnd not in row["rounds_blocking"]:
            row["rounds_blocking"].append(rnd)
        row.update({"status": "open", "last_evidence": b.get("evidence", "")[:300], "loop_back": b.get("loop_back"),
                    "fixed_when": b.get("fixed_when")})
    for fid in judge.get("resolved") or []:
        if fid in ledger:
            ledger[fid]["status"] = "fixed"
            ledger[fid]["fixed_round"] = rnd
    for i, lg in enumerate(judge.get("logged") or []):
        fid = lg.get("id") or f"logged-r{rnd}-{i + 1}"
        ledger.setdefault(fid, {"summary": lg.get("summary", ""), "first_round": rnd, "rounds_blocking": [],
                                "status": "logged"})
    return ledger


def set_status(project, mid, verdict, fp):
    ms = project / "docs/project/milestones.md"
    if not ms.is_file():
        return
    text = ms.read_text(encoding="utf-8")
    block = milestone_block(text, mid)
    if not block:
        return
    new = block
    if verdict == "CHANGES":
        new = re.sub(r"^Status:\s*\S+", "Status: changes", new, count=1, flags=re.M)
    if verdict == "ACCEPT-READY":
        # The tick names the candidate that passed; a later passing round replaces it.
        new = re.sub(r"gate-passed \[[ x]\]( \([^)]*\))?", f"gate-passed [x] ({fp})", new, count=1)
    else:
        # The latest round did not pass, so no candidate of this milestone stands as gate-passed.
        new = re.sub(r"gate-passed \[x\]( \([^)]*\))?", "gate-passed [ ]", new, count=1)
    if new != block:
        ms.write_text(text.replace(block, new), encoding="utf-8")


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0]).resolve()
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    intent_only = "--intent-only" in argv
    for k in ("--milestone", "--round", "--evidence", "--fingerprint"):
        if k not in opts:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    mid, rnd, ev, fp = opts["--milestone"], int(opts["--round"]), Path(opts["--evidence"]), opts["--fingerprint"]
    if not ev.is_dir():
        print(f"gate_report: no evidence folder {ev}", file=sys.stderr)
        return 1
    reviews = project / "docs/project/reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    ledger_path = reviews / f"{mid}.findings.json"
    ledger = load(ledger_path) or {}
    try:
        verdict, reasons, exceptions, judge, summaries = compute(project, mid, rnd, ev, ledger, intent_only)
        if not intent_only:
            ledger = update_ledger(ledger, judge, rnd)
            ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
        diff_counts = {}
        for r in (judge or {}).get("intent_diff") or []:
            diff_counts[st(r)] = diff_counts.get(st(r), 0) + 1
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        # A checker wrote JSON of the wrong shape (a string where a list belongs, a row that is not an object).
        verdict, judge, summaries, diff_counts = "INCONCLUSIVE", None, {}, {}
        reasons = [f"a checker's JSON has the wrong shape ({exc.__class__.__name__}: {str(exc)[:120]}); "
                   "run the round again"]
        exceptions = []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {"milestone": mid, "round": rnd, "fingerprint": fp, "verdict": verdict,
              "judge_verdict": (judge or {}).get("verdict"), "reasons": reasons, "exceptions": exceptions,
              "intent_diff": diff_counts, "checkers": {c: (s or {}).get("status") for c, s in summaries.items()},
              "sessions": {c: (s or {}).get("session_id") for c, s in summaries.items()},
              "written": stamp}
    if verdict == "ACCEPT-READY" and not intent_only:
        result["evidence_line"] = evidence_line(mid, checker_json(ev, "code-verifier"), load(ev / "layer1.json") or {},
                                                judge or {})
    (ev / "verdict.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    if intent_only:
        with open(reviews / "intent-ledger.md", "a", encoding="utf-8") as f:
            f.write(f"- {stamp} · {mid} · intent check r{rnd} · {verdict} · "
                    + (" · ".join(f"{k} {v}" for k, v in diff_counts.items()) or "no rows") + f" · {ev}\n")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    review = reviews / f"{mid}.md"
    if not review.exists():
        review.write_text(f"# Review of {mid}\n")
    blocking = [f"{b.get('id')} {b.get('summary', '')[:100]} (loop back: {b.get('loop_back')})"
                for b in (judge or {}).get("blocking") or []]
    block = [f"\n## Round {rnd} · {stamp} · fingerprint {fp}",
             f"Verdict: {verdict} (computed; judge said {result['judge_verdict']})",
             "Checkers: " + " · ".join(f"{c} {s}" for c, s in result["checkers"].items() if s),
             "Intent diff: " + (" · ".join(f"{k} {v}" for k, v in diff_counts.items()) or "none"),
             "Reasons: " + ("; ".join(reasons) or "none"),
             "Blocking: " + ("; ".join(blocking) or "none"),
             "Exceptions: " + ("; ".join(exceptions) or "none"),
             f"Evidence: {ev}", ""]
    with open(review, "a", encoding="utf-8") as f:
        f.write("\n".join(block))
    set_status(project, mid, verdict, fp)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
