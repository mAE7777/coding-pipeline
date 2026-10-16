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
Deterministic checks that were skipped or not run are listed as exceptions, as is a checker served by another
model than it asked for (model_mismatch) or retried on the escalate model.
When the judge's own verdict is stricter than the computed one it is recorded as an exception and the
result is INCONCLUSIVE (its verdict does not follow from its findings); when it is looser, the computed
verdict stands and the disagreement is listed.
A focused round (<dir>/scope.json says "focused", from regate_scope.py): the loyal-evaluator's pass 1 and pass 2
are CARRIED from the earlier round scope.json names, read from its paths, not this folder; a carried summary
or result that is missing, not status OK, or without its round and fingerprint -> INCONCLUSIVE. The
code-verifier's result is the re-verify: the review JSON's keys plus "reverify", one row per scope finding (or
hotfix fix) with FIXED or NOT_FIXED and its evidence. A scope item with no row, or another status ->
INCONCLUSIVE. NOT_FIXED keeps the item blocking in this round even when the judge does not list it, so the
two-round rule (4) applies to it; FIXED with no judge block marks the ledger entry fixed. New findings in the
delta are triaged like any review finding.
The judge's blocking findings may carry "files" (the paths a fix must touch); the ledger keeps them, with the
class, severity, and where of the reviewer finding the entry names. A finding without files makes the next
round full (regate_scope.py).
At ACCEPT-READY, baseline.py changed <project> M<k> --write records the files the milestone changed (for scoped
regression demos); a failure there is an exception and never changes the verdict.
The round block lists the round's scope with its reasons, and for each checker step its route, the model and
effort it asked for, the model that served it, and whether its retry escalated (or that it was CARRIED).
Prints the verdict JSON, and for ACCEPT-READY the evidence line, built from what each checker said:
  gate M<k> ACCEPT-READY=SHIP · code-verifier SHIP · loyal-evaluator SHIP · gate-judge SHIP · gate.sh 0-FAIL
(the code-verifier part reads "code-verifier FAIL (overruled: ...)" when its FAIL was triaged as logged, the
loyal-evaluator part "loyal-evaluator CARRIED (r<n>)" in a focused round, and the gate.sh part names its status
when it did not pass).
--intent-only (the standalone intent check): only the loyal-evaluator's three passes and the judge are required, the
copies and deterministic layer are not, the two-round rule does not apply, the milestone's status is not
changed, and the round is logged as one line in docs/project/reviews/intent-ledger.md instead of the review file.
Exit 0 when a verdict was written (whatever it is), 1 when the evidence folder is unusable, 2 on bad usage.
"""
import datetime
import hashlib
import json
import re
import subprocess
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
CARRIED = ("loyal-evaluator", "loyal-evaluator-pass2")  # in a focused round, from the last full round
REVERIFY = {"FIXED", "NOT_FIXED"}


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


INTENT_CHECKERS = ("loyal-evaluator", "loyal-evaluator-pass2", "loyal-evaluator-pass3", "gate-judge")
# Finding classes the judge must triage (block or log) at any severity but low; clarity is usually logged, but it
# may never vanish between the reviewer and the verdict.
REVIEW_BLOCKING = {"correctness", "requirement", "security", "wiring", "silent-degradation", "quality-substitution",
                   "placeholder-unconsented", "interface", "clarity"}
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


def checker_rules(review, demo, judge, mid, not_fixed=()):
    """(forced CHANGES reasons, INCONCLUSIVE reasons) that hold whatever the judge concluded. not_fixed: the
    scope items a re-verify reported NOT_FIXED (each one is something named)."""
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
    if str(review.get("verdict")).upper() == "FAIL" and not (findings or failing or broken or not_fixed):
        unsure.append("the code-verifier said FAIL but named no finding, failing row, or broken wiring to triage")
    return changes, unsure


def evidence_line(mid, review, layer1, judge, carried_round=None):
    """The ACCEPT-READY line, each part saying what that checker actually reported."""
    if str((review or {}).get("verdict")).upper() == "PASS":
        cv = "code-verifier SHIP"
    else:
        logged = [e.get("id") for e in judge.get("logged") or [] if e.get("id")]
        cv = f"code-verifier {(review or {}).get('verdict', 'missing')} (overruled: {', '.join(logged) or 'no logged ids'})"
    gs = next((c.get("status") for c in layer1.get("checks", []) if c.get("name") == "gate.sh"), "NOT_RUN")
    gs = "gate.sh 0-FAIL" if gs in ("PASS", "WARN") else f"gate.sh {gs}"
    le = f"loyal-evaluator CARRIED (r{carried_round})" if carried_round is not None else "loyal-evaluator SHIP"
    return f"gate {mid} ACCEPT-READY=SHIP \u00b7 {cv} \u00b7 {le} \u00b7 gate-judge SHIP \u00b7 {gs}"


def carried_summaries(scope):
    """The carried evaluator summaries of a focused round ({stem: summary with a "carried" record}) and what makes
    them unusable."""
    out, problems = {}, []
    for stem in CARRIED:
        c = (scope.get("carried") or {}).get(stem)
        c = c if isinstance(c, dict) else {}
        where = f"{stem} CARRIED from r{c.get('round')}"
        s = load(c["summary"]) if c.get("summary") else None
        if not isinstance(s, dict):
            problems.append(f"{where}: no summary at {c.get('summary') or '(no path in scope.json)'}")
            s = {}
        elif s.get("status") != "OK":
            problems.append(f"{where} ended {s.get('status')}, so it cannot stand for this round")
        if not c.get("result") or not Path(c["result"]).is_file():
            problems.append(f"{where}: no result at {c.get('result') or '(no path in scope.json)'}")
        if not c.get("round") or not c.get("fingerprint"):
            problems.append(f"{stem} CARRIED: scope.json does not record the round and fingerprint it ran on")
        out[stem] = {**s, "carried": {"round": c.get("round"), "fingerprint": c.get("fingerprint"),
                                      "result": c.get("result")}}
    return out, problems


def reverify_rows(scope, review):
    """(INCONCLUSIVE reasons, NOT_FIXED items, FIXED ids) from a focused round's re-verify against its scope."""
    items = [(f.get("id"), "finding", f) for f in scope.get("findings") or [] if isinstance(f, dict)] + \
        [(f.get("id"), "fix", f) for f in scope.get("fixes") or [] if isinstance(f, dict)]
    if not items:
        return [], [], []
    rows = review.get("reverify")
    if not isinstance(rows, list):
        return ["the re-verify result has no reverify rows (one per scope finding or fix)"], [], []
    by_id = {key(x.get("id")): x for x in rows if isinstance(x, dict)}
    unsure, not_fixed, fixed = [], [], []
    for fid, what, item in items:
        row = by_id.get(key(fid))
        if row is None:
            unsure.append(f"the re-verify has no row for {what} {fid}")
        elif st(row) not in REVERIFY:
            unsure.append(f"the re-verify row for {fid} has status {st(row) or 'none'}, not FIXED or NOT_FIXED")
        elif st(row) == "NOT_FIXED":
            not_fixed.append((fid, what, item, row))
        else:
            fixed.append(fid)
    return unsure, not_fixed, fixed


def keep_blocking(judge, not_fixed, ledger, exceptions):
    """A scope item the re-verify reports NOT_FIXED stays blocking this round, whether or not the judge lists it."""
    blocking = list(judge.get("blocking") or [])
    have = {key(b.get("id")) for b in blocking if isinstance(b, dict)}
    for fid, what, item, row in not_fixed:
        if key(fid) in have:
            continue
        led = ledger.get(fid) or {}
        exceptions.append(f"{fid}: the re-verify says NOT_FIXED, so it stays blocking although the judge did not "
                          "list it")
        blocking.append({"id": fid, "summary": item.get("summary") or item.get("title") or led.get("summary", ""),
                         "evidence": f"re-verify NOT_FIXED: {str(row.get('evidence', ''))[:240]}",
                         "loop_back": led.get("loop_back") or "fix",
                         "fixed_when": item.get("fixed_when") or led.get("fixed_when") or item.get("reproduction"),
                         "files": item.get("files") or led.get("files"),
                         **{k: item.get(k) or led.get(k) for k in ("class", "severity", "where")}})
    judge["blocking"] = blocking


def compute(project, mid, rnd, ev, ledger, intent_only=False):
    reasons, exceptions = [], []
    scope = None if intent_only else load(ev / "scope.json")
    focused = isinstance(scope, dict) and scope.get("scope") == "focused"
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
        reasons.append("deterministic layer: " + ", ".join(
            c["name"] + (f" ({c['detail']})" if c.get("detail") else "") for c in layer1.get("checks", [])
            if c.get("status") == "FAIL"))
    if reasons:
        return "CHANGES", reasons, exceptions, None, {}
    if layer1.get("status") == "NOT_RUN":
        return "INCONCLUSIVE", ["deterministic layer did not run: " + "; ".join(
            f"{c['name']} ({c.get('reason', '')})" for c in layer1.get("checks", []) if c.get("status") == "NOT_RUN")
            + "; run the round again"], exceptions, None, {}
    for c in layer1.get("checks", []):
        if c.get("status") in ("SKIP", "NOT_RUN"):
            exceptions.append(f"deterministic check {c.get('name')} {c.get('status')}: "
                              f"{str(c.get('reason') or c.get('detail') or '')[:120]}")
    # A focused round runs no evaluator: its pass 1 and pass 2 are carried from the round scope.json names.
    required = INTENT_CHECKERS if intent_only else tuple(c for c in CHECKERS if not (focused and c in CARRIED))
    summaries = {c: load(ev / f"{c}.summary.json") for c in required}
    for c, s in summaries.items():
        if s is None:
            continue
        if s.get("pack_missing"):
            exceptions.append(f"{c}: inputs not provided, so the checks on them are NOT_RUN: {', '.join(s['pack_missing'])}")
        if s.get("family_switch"):
            exceptions.append(f"{c}: ran on {s['family']} because {s['family_switch']['from']} was unavailable "
                              f"({s['family_switch']['reason']})")
        if s.get("model_mismatch"):
            exceptions.append(f"{c}: asked for {s.get('requested_model')}, served by {s.get('served_model')}")
        if s.get("escalated"):
            exceptions.append(f"{c}: its retry ran on {s.get('requested_model')} at {s.get('requested_effort')} "
                              f"({str(s.get('escalation_reason', ''))[:160]})")
    for c, s in summaries.items():
        if s and s.get("status") == "BLOCKED":
            return "BLOCKED", [f"{c}: {s.get('reason')}"], exceptions, None, summaries
    for c, s in summaries.items():
        if s and s.get("status") in ("LEAK", "ERROR", "INCONCLUSIVE", "UNAVAILABLE"):
            reasons.append(f"{c}: {s['status']} {s.get('reason') or s.get('canary_hits') or ''}".strip())
    missing = [c for c in required if summaries.get(c) is None]
    if missing:
        reasons.append("did not run: " + ", ".join(missing))
    if focused:
        carried, problems = carried_summaries(scope)
        reasons += problems
        merged = {**summaries, **carried}
        summaries = {c: merged.get(c) for c in CHECKERS}
    judge = last_json((ev / "gate-judge.result.md").read_text(encoding="utf-8")) \
        if (ev / "gate-judge.result.md").is_file() else None
    if judge is None or str(judge.get("verdict")).strip().upper() not in ("ACCEPT-READY", "CHANGES", "BLOCKED",
                                                                           "INCONCLUSIVE"):
        reasons.append("no valid verdict JSON from gate-judge")
    review = demo = None
    not_fixed, fixed = [], []
    if not intent_only:
        review, demo = checker_json(ev, "code-verifier"), checker_json(ev, "code-verifier-demo")
        if review and isinstance(review.get("verdict"), str):
            review["verdict"] = review["verdict"].strip().upper()
        if not review or review.get("verdict") not in ("PASS", "FAIL", "INCONCLUSIVE"):
            reasons.append("no valid verdict JSON from the code-verifier")
        elif review.get("verdict") == "INCONCLUSIVE":
            reasons.append("the code-verifier's own verdict is INCONCLUSIVE")
        elif focused:
            unsure_rv, not_fixed, fixed = reverify_rows(scope, review)
            reasons += unsure_rv
        if not demo or not demo.get("steps"):
            reasons.append("no demo steps from the demo run")
    if reasons:
        return "INCONCLUSIVE", reasons, exceptions, judge, summaries
    if intent_only:
        forced = [] if (judge.get("purpose") or {}).get("same_product") is not False else \
            ["the evaluator's purpose guess describes a different product (purpose drift)"]
        unsure = []
    else:
        if not_fixed:
            keep_blocking(judge, not_fixed, ledger, exceptions)
        if fixed:
            # FIXED and not blocked again: the ledger entry is fixed even when the judge did not list it resolved.
            now = {key(b.get("id")) for b in judge.get("blocking") or [] if isinstance(b, dict)}
            judge["resolved"] = list(judge.get("resolved") or []) + \
                [f for f in fixed if f in ledger and key(f) not in now and f not in (judge.get("resolved") or [])]
        forced, unsure = checker_rules(review, demo, judge, mid, not_fixed)
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


def model_record(s):
    """What a checker step asked for and what served it (plan 7.3 step 1), from its summary."""
    if not s:
        return None
    rec = {k: s.get(k) for k in ("route", "requested_model", "requested_effort", "served_model", "family")}
    rec["escalated"] = bool(s.get("escalated"))
    if s.get("route_applies") is False:
        rec["route_applies"] = False
    if s.get("carried"):
        rec["carried_from"] = s["carried"].get("round")
    return rec


def model_line(name, s):
    """One line of the round block: the step's route, asked model and effort, served model, and escalation."""
    if not s:
        return f"- {name}: did not run"
    head = f"- {name}" + (f" (CARRIED from r{s['carried'].get('round')}, {s['carried'].get('fingerprint')})"
                          if s.get("carried") else "") + ": "
    if s.get("route_applies") is False:
        body = f"route {s.get('route', '?')} does not apply; the {s.get('family')} family keeps its own model and effort"
    else:
        body = (f"route {s.get('route', '?')}, asked {s.get('requested_model', '?')} at "
                f"{s.get('requested_effort', '?')}, served {s.get('served_model') or 'not named'}")
    if s.get("escalated"):
        esc = f"escalated ({str(s.get('escalation_reason', ''))[:160]})"
    elif s.get("escalation_reason"):
        esc = f"retried, not escalated ({str(s['escalation_reason'])[:160]})"
    else:
        esc = "not escalated"
    return head + body + ", " + esc


def update_ledger(ledger, judge, rnd, review=None):
    if not judge:
        return ledger
    findings = [f for f in (review or {}).get("findings") or [] if isinstance(f, dict)]
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
        # The paths a fix must touch (regate_scope.py bounds a focused round by them); none given keeps what an
        # earlier round said, and none at all makes the next round full.
        files = b.get("files")
        files = [files] if isinstance(files, str) else files
        files = [str(f).strip() for f in files or [] if str(f).strip()] if isinstance(files, list) else []
        row["files"] = files or row.get("files") or None
        source = next((f for f in findings if mentioned(f, [b])), {})
        for k in ("class", "severity", "where"):
            row[k] = b.get(k) or source.get(k) or row.get(k)
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
    from project_policy import require, read as policy, valid, OFF_TEXT  # noqa: E402
    if not require(project):
        return 3
    lease = policy(project)
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
    ledger_path = reviews / f"{mid}.findings.json"
    ledger = load(ledger_path) or {}
    try:
        verdict, reasons, exceptions, judge, summaries = compute(project, mid, rnd, ev, ledger, intent_only)
        if not intent_only:
            ledger = update_ledger(ledger, judge, rnd, checker_json(ev, "code-verifier"))
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
    if not valid(lease):
        print(OFF_TEXT, file=sys.stderr)
        return 3
    reviews.mkdir(parents=True, exist_ok=True)
    if not intent_only and judge is not None:
        ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    scope = None if intent_only else load(ev / "scope.json")
    scope = scope if isinstance(scope, dict) else None
    carried = {c: s["carried"] for c, s in summaries.items() if s and s.get("carried")}
    if verdict == "ACCEPT-READY" and not intent_only:
        # The files this milestone changed, so a later milestone replays its demo only when it touches them.
        try:
            ch = subprocess.run([sys.executable, str(HERE / "baseline.py"), "changed", str(project), mid, "--write"],
                                capture_output=True, text=True, timeout=600)
            failed = None if ch.returncode == 0 else f"exit {ch.returncode}: {(ch.stderr or ch.stdout).strip()[-200:]}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            failed = f"{exc.__class__.__name__}: {exc}"
        if failed:
            exceptions.append(f"baseline.py changed {mid} --write failed ({failed}); the files this milestone "
                              "changed are not recorded")
    result = {"milestone": mid, "round": rnd, "fingerprint": fp, "verdict": verdict,
              "judge_verdict": (judge or {}).get("verdict"), "reasons": reasons, "exceptions": exceptions,
              "intent_diff": diff_counts, "checkers": {c: (s or {}).get("status") for c, s in summaries.items()},
              "sessions": {c: (s or {}).get("session_id") for c, s in summaries.items()},
              "models": {c: model_record(s) for c, s in summaries.items()},
              "written": stamp}
    if scope:
        result["scope"] = {k: scope.get(k) for k in ("scope", "kind", "reasons", "since", "changed_lines")}
    if carried:
        result["carried"] = carried
    if intent_only:
        # Which draft of the intent this check read, so a later edit shows the check is out of date.
        intent = project / "docs/project/intent.md"
        result["intent_sha"] = hashlib.sha256(intent.read_bytes()).hexdigest() if intent.is_file() else None
    if verdict == "ACCEPT-READY" and not intent_only:
        result["evidence_line"] = evidence_line(mid, checker_json(ev, "code-verifier"), load(ev / "layer1.json") or {},
                                                judge or {}, (carried.get("loyal-evaluator") or {}).get("round"))
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
             "Scope: " + (f"{scope.get('scope')}" + (f" ({scope['kind']})" if scope.get("kind") else "") + " \u00b7 "
                          + "; ".join(scope.get("reasons") or []) if scope else "full (no scope record)"),
             "Checkers: " + " \u00b7 ".join(
                 f"{c} CARRIED r{carried[c]['round']} {s}" if c in carried else f"{c} {s}"
                 for c, s in result["checkers"].items() if s),
             "Models:", *[model_line(c, s) for c, s in summaries.items()],
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
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
