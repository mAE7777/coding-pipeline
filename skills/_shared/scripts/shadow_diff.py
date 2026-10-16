#!/usr/bin/env python3
"""Compare a checker run with its shadow run, and say from the shadow log when a candidate setting may be promoted.

Usage:
  shadow_diff.py compare <primary.result.md> <shadow.result.md> --role <role> [--json]
  shadow_diff.py summary [--log <file>] [--json]

A shadow run is the same checker with the same pack on a candidate model or effort, run by run_isolated.py after
the main run (the personal override's shadow section, or --shadow; models.py). Only the main run's result counts.

compare reads each run's last fenced JSON block (gate_report.py's last_json) and compares, by role:
  code-verifier    done_examples and must_not_lose (by id), mechanisms (by name), wiring (by component),
                   findings, and the verdict; a demo run's steps (by milestone and step)
  gate-judge       intent_diff rows (by id), blocking and logged findings, the verdict, purpose.same_product
  cold-reader      earlier items (settled or not), divergences, fidelity items, contradictions, missing, and
                   the verdict
  claim-verifier   claims (by id)
  change-reviewer  findings, checks_weakened, the verdict, kind, kind_ok, and the root cause, reproduction,
                   and workaround statuses
  other roles      findings and the verdict, when present
A row reports a defect when its status is not clean (HOLDS; proven or parked-unreachable for wiring; CONFIRMED for
a claim; settled for an earlier item); every finding reports one. Findings match on id when both carry one (and
their class and file agree), else on class and the file named in where, else on class and summary. A judge's
blocking and logged entries are one class, blocking ranked above logged.
Output: agreements; "shadow missed" (the primary reported a defect and the shadow did not: a clean or absent row,
an unmatched finding, or a matched finding the shadow ranked low, minor, or logged where the primary ranked it
higher); "shadow extra" (the reverse); differences (both reported it, differently, or a clean row only one run
has); and the verdict fields that differ.
Exit 0 when both parse (whatever they say), 1 when one does not (named), 2 on bad usage.

summary reads the shadow log (default ~/.claude/.pipeline-shadow.jsonl, one line per shadow run, appended by
run_isolated.py) and prints, per route and shadow setting: runs, distinct rounds compared (distinct evidence
folders), total misses and extras, and failed shadow runs (the shadow did not end OK, or its result could not be
compared). Runs under .evidence/fixtures/ (agent_fixtures.py) are not real work and are left out. It says
"ready to promote" only with at least 3 distinct rounds compared, zero misses, and no failed shadow run (plan
7.3 step 4: no case where the candidate missed what today's setting caught); otherwise "not ready" with the
reason. Whether today's setting was itself right about a miss is the owner's call, from that
round's <stem>.shadow-diff.json. Promotion stays manual: a /evolve change to skills/_shared/models.json.
Exit 0, 1 when the log cannot be read, 2 on bad usage.
"""
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from gate_report import last_json  # noqa: E402

READY_ROUNDS = 3
FIXTURE_RUN = re.compile(r"/\.evidence/fixtures/")  # agent_fixtures.py's runs: logged, never counted as real work
# Rows: (group, key fields, clean statuses). Any other status reports a defect.
ROWS = {
    "code-verifier": (("done_examples", ("id",), {"HOLDS"}), ("must_not_lose", ("id",), {"HOLDS"}),
                      ("mechanisms", ("name",), {"HOLDS"}),
                      ("wiring", ("component",), {"PROVEN", "PARKED-UNREACHABLE"}),
                      ("steps", ("milestone", "step"), {"HOLDS"})),
    "gate-judge": (("intent_diff", ("id",), {"HOLDS"}),),
    "claim-verifier": (("claims", ("id",), {"CONFIRMED"}),),
    "loyal-evaluator": (("items", ("id",), {"HOLDS"}),),
    "cold-reader": (("previous", ("item",), {"SETTLED"}),),
}
# Findings: (group, the class every entry of the group takes, or None for the entry's own class or kind).
FINDINGS = {
    "code-verifier": (("findings", None),),
    "gate-judge": (("blocking", "judge"), ("logged", "judge")),
    "cold-reader": (("divergences", "divergence"), ("fidelity", None), ("contradictions", "contradiction"),
                    ("missing", "missing"), ("unresolvable_references", "unresolvable-reference")),
    "change-reviewer": (("findings", None), ("checks_weakened", "weakened-check")),
    "claim-verifier": (),
    "loyal-evaluator": (),
}
VERDICT = {
    "code-verifier": ("verdict",),
    "gate-judge": ("verdict", "purpose.same_product"),
    "cold-reader": ("verdict",),
    "change-reviewer": ("verdict", "kind", "kind_ok", "root_cause.status", "reproduction.status",
                        "session_workaround.status"),
    "claim-verifier": (),
    "loyal-evaluator": (),
}
# A finding ranked 1 is one the gate lets pass without triage (low, minor, a judge's logged entry).
RANK = {"blocking": 3, "high": 3, "material": 3, "medium": 2, "low": 1, "minor": 1, "logged": 1}
ABSENT = object()


def key(value):
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip().lower()


def where_key(value):
    """The file a where names (line numbers dropped), or the quoted text, normalized."""
    w = key(value)
    if w and " " not in w:
        w = re.sub(r"(#l\d+.*|(:\d+)+(-\d+)?)$", "", w)
    return w


def text_key(value):
    return re.sub(r"[^a-z0-9]+", " ", key(value)).strip()[:80]


def base_role(role):
    """The role of a run stem (code-verifier-demo, loyal-evaluator-pass2) or a role name."""
    return re.sub(r"(-demo|-pass\d+)$", "", str(role))


def status_of(group, row):
    if group == "previous":
        return "SETTLED" if row.get("settled") is True else "OPEN"
    return str(row.get("status") or "").strip().upper() or "NO STATUS"


def rows_of(data, role):
    """{(group, key): (shown key, status, clean statuses)} of every status row the role reports."""
    out = {}
    for group, fields, clean in ROWS.get(role, ()):
        for row in data.get(group) or []:
            if not isinstance(row, dict):
                continue
            shown = "-".join(str(row.get(f, "")) for f in fields)
            out[(group, tuple(key(row.get(f)) for f in fields))] = (shown, status_of(group, row), clean)
    return out


def findings_of(data, role):
    out = []
    for group, klass in FINDINGS.get(role, (("findings", None),)):
        for f in data.get(group) or []:
            f = {"summary": f} if isinstance(f, str) else f
            if not isinstance(f, dict):
                continue
            where = f.get("where") or f.get("unit") or f.get("turn") or f.get("quote") or f.get("quote_a") or ""
            summary = f.get("summary") or f.get("point") or f.get("what") or f.get("dossier_says") or \
                f.get("reading_a") or f.get("quote") or ""
            severity = group if klass == "judge" else f.get("severity")
            out.append({"group": group, "id": f.get("id"), "class": key(klass or f.get("class") or f.get("kind") or
                                                                         group).replace("_", "-").replace(" ", "-"),
                        "severity": key(severity) or None, "where": where_key(where), "summary": text_key(summary),
                        "show": {k: v for k, v in (("id", f.get("id")), ("severity", severity),
                                                   ("where", str(where)[:120] or None),
                                                   ("summary", str(summary)[:160] or None)) if v}})
    return out


def match(prim, shad):
    """Pairs of (primary, shadow) findings, and the unmatched ones of each side."""
    left_p, left_s, pairs = list(range(len(prim))), list(range(len(shad))), []

    def same_file(p, s):
        return not (p["where"] and s["where"]) or p["where"] == s["where"]

    tests = (lambda p, s: p["id"] and s["id"] and key(p["id"]) == key(s["id"]) and p["class"] == s["class"]
             and same_file(p, s),
             lambda p, s: p["class"] == s["class"] and p["where"] and p["where"] == s["where"],
             lambda p, s: p["class"] == s["class"] and p["summary"] and p["summary"] == s["summary"])
    for test in tests:
        for i in list(left_p):
            j = next((j for j in left_s if test(prim[i], shad[j])), None)
            if j is not None:
                pairs.append((prim[i], shad[j]))
                left_p.remove(i)
                left_s.remove(j)
    return pairs, [prim[i] for i in left_p], [shad[j] for j in left_s]


def field(data, dotted):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ABSENT
        cur = cur[part]
    return cur


def same_value(a, b):
    norm = (lambda v: v.strip().upper() if isinstance(v, str) else v)
    return norm(a) == norm(b)


def compare(primary, shadow, role):
    """What the shadow agreed with, missed, added, and said differently, from the two runs' JSON."""
    role = base_role(role)
    out = {"role": role, "agreements": [], "shadow_missed": [], "shadow_extra": [], "differences": [], "verdict": []}
    rp, rs = rows_of(primary, role), rows_of(shadow, role)
    for k in sorted(set(rp) | set(rs)):
        shown, _, clean = rp.get(k) or rs[k]
        p, s = (rp[k][1] if k in rp else None), (rs[k][1] if k in rs else None)
        item = {"kind": "row", "group": k[0], "key": shown, "primary": p, "shadow": s}
        p_defect, s_defect = p is not None and p not in clean, s is not None and s not in clean
        if p == s:
            out["agreements"].append(item)
        elif p_defect and not s_defect:
            out["shadow_missed"].append(item)
        elif s_defect and not p_defect:
            out["shadow_extra"].append(item)
        else:
            out["differences"].append(item)
    pairs, only_p, only_s = match(findings_of(primary, role), findings_of(shadow, role))
    for p, s in pairs:
        item = {"kind": "finding", "class": p["class"], "primary": p["show"], "shadow": s["show"]}
        if p["severity"] == s["severity"]:
            out["agreements"].append(item)
            continue
        a, b = RANK.get(p["severity"] or ""), RANK.get(s["severity"] or "")
        if a and b and a > 1 >= b:
            out["shadow_missed"].append({**item, "why": f"the shadow ranked it {s['severity']}"})
        elif a and b and b > 1 >= a:
            out["shadow_extra"].append({**item, "why": f"the shadow ranked it {s['severity']}"})
        else:
            out["differences"].append({**item, "why": "another severity"})
    out["shadow_missed"] += [{"kind": "finding", "class": p["class"], "primary": p["show"], "shadow": None}
                             for p in only_p]
    out["shadow_extra"] += [{"kind": "finding", "class": s["class"], "primary": None, "shadow": s["show"]}
                            for s in only_s]
    for name in VERDICT.get(role, ("verdict",)):
        a, b = field(primary, name), field(shadow, name)
        if a is ABSENT and b is ABSENT:
            continue
        a, b = (None if a is ABSENT else a), (None if b is ABSENT else b)
        out["verdict"].append({"field": name, "primary": a, "shadow": b, "same": same_value(a, b)})
    out["counts"] = {"agreements": len(out["agreements"]), "misses": len(out["shadow_missed"]),
                     "extras": len(out["shadow_extra"]), "differences": len(out["differences"]),
                     "verdict_differences": sum(1 for v in out["verdict"] if not v["same"])}
    return out


def read_result(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot be read ({exc.strerror or exc})"
    data = last_json(text)
    if not isinstance(data, dict):
        return None, "holds no fenced JSON block that parses"
    return data, None


def compare_files(primary_path, shadow_path, role):
    """(the comparison, 0) when both results parse; (a record naming the one that does not, 1) otherwise."""
    p, p_err = read_result(primary_path)
    s, s_err = read_result(shadow_path)
    base = {"role": base_role(role), "primary_result": str(primary_path), "shadow_result": str(shadow_path)}
    if p_err or s_err:
        said = [f"the {side} result {path} {err}" for side, path, err in
                (("primary", primary_path, p_err), ("shadow", shadow_path, s_err)) if err]
        return {**base, "error": "; ".join(said), "unparsed": [side for side, err in
                                                              (("primary", p_err), ("shadow", s_err)) if err]}, 1
    return {**base, **compare(p, s, role)}, 0


def describe_item(item):
    if item["kind"] == "row":
        return (f"{item['group']} {item['key']}: primary {item['primary'] or 'no row'}, "
                f"shadow {item['shadow'] or 'no row'}")
    p, s = item.get("primary"), item.get("shadow")
    one = p or s
    head = f"finding {item['class']}" + (f" {one['id']}" if one.get("id") else "") + \
        (f" at {one['where']}" if one.get("where") else "")
    if p and s:
        return f"{head}: primary {p.get('severity') or '-'}, shadow {s.get('severity') or '-'}" + \
            (f" ({item['why']})" if item.get("why") else "")
    said = f" \"{one['summary'][:80]}\"" if one.get("summary") else ""
    return f"{head}{said}: {'only the primary' if p else 'only the shadow'} reported it"


def print_compare(res):
    c = res["counts"]
    verdict = [v for v in res["verdict"] if not v["same"]]
    print(f"shadow_diff {res['role']}: {c['agreements']} agree, {c['misses']} shadow missed, {c['extras']} shadow "
          f"extra, {c['differences']} differ" + ("; verdict differs" if verdict else ""))
    for title, name in (("shadow missed", "shadow_missed"), ("shadow extra", "shadow_extra"),
                        ("differences", "differences")):
        if res[name]:
            print(f"{title}:")
            for item in res[name]:
                print(f"  {describe_item(item)}")
    for v in verdict:
        print(f"verdict {v['field']}: primary {v['primary']}, shadow {v['shadow']}")


def log_path():
    return Path.home() / ".claude/.pipeline-shadow.jsonl"


def round_of(path):
    """The round number an evidence path names (.../r3, plan-r2), or None."""
    for part in reversed(Path(path).parts):
        m = re.fullmatch(r"(?:.+-)?r(\d+)", part)
        if m:
            return int(m.group(1))
    return None


def record(entry, log=None):
    """Append one shadow run to the log, with the time."""
    path = Path(log) if log else log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return path


def summarize(entries):
    """Per route and shadow setting: runs, rounds compared, misses, extras, failures, and readiness."""
    groups = {}
    for e in entries:
        sh = e.get("shadow") if isinstance(e.get("shadow"), dict) else {}
        g = groups.setdefault((str(e.get("route")), str(sh.get("model")), str(sh.get("effort"))),
                              {"runs": 0, "rounds": set(), "misses": 0, "extras": 0, "failed": 0, "against": set(),
                               "fixture_runs": 0})
        if FIXTURE_RUN.search(str(e.get("evidence"))):
            g["fixture_runs"] += 1  # a fixture is not real work: the pooled comparison (7.3 step 2) measures those
            continue
        g["runs"] += 1
        pr = e.get("primary") if isinstance(e.get("primary"), dict) else {}
        g["against"].add(f"{pr.get('model')} {pr.get('effort')}")
        misses, extras = e.get("misses"), e.get("extras")
        if sh.get("status") != "OK" or not isinstance(misses, int) or not isinstance(extras, int):
            g["failed"] += 1
            continue
        g["rounds"].add(str(e.get("evidence")))
        g["misses"] += misses
        g["extras"] += extras
    rows = []
    for (route, model, effort), g in sorted(groups.items()):
        why = []
        if g["misses"]:
            why.append(f"{g['misses']} miss(es): the shadow missed what today's setting reported (see each round's "
                       "shadow-diff.json)")
        if g["failed"]:
            why.append(f"{g['failed']} shadow run(s) did not end OK or could not be compared")
        if len(g["rounds"]) < READY_ROUNDS:
            why.append(f"{len(g['rounds'])} of {READY_ROUNDS} distinct rounds compared")
        rows.append({"route": route, "shadow": {"model": model, "effort": effort}, "runs": g["runs"],
                     "rounds": len(g["rounds"]), "misses": g["misses"], "extras": g["extras"], "failed": g["failed"],
                     "fixture_runs_ignored": g["fixture_runs"], "against": sorted(g["against"]), "ready": not why,
                     "why_not": why})
    return rows


def read_log(path):
    entries, bad = [], 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(e, dict):
            entries.append(e)
        else:
            bad += 1
    return entries, bad


def cmd_summary(argv):
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv and (len(argv) != 2 or argv[0] != "--log"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(argv[1]) if argv else log_path()
    try:
        entries, bad = read_log(path) if path.exists() else ([], 0)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"shadow_diff: the shadow log {path} cannot be read: {exc}", file=sys.stderr)
        return 1
    rows = summarize(entries)
    if as_json:
        print(json.dumps({"log": str(path), "unreadable_lines": bad, "settings": rows}, indent=2))
        return 0
    print(f"shadow summary of {path}" + (f" ({bad} unreadable line(s) skipped)" if bad else ""))
    if not rows:
        print("no shadow runs recorded")
        return 0
    fmt = "{:<26} {:<24} {:>4} {:>6} {:>6} {:>6} {:>6}  {}"
    print(fmt.format("route", "shadow", "runs", "rounds", "misses", "extras", "failed", "state"))
    for r in rows:
        state = "ready to promote" if r["ready"] else "not ready: " + "; ".join(r["why_not"])
        print(fmt.format(r["route"][:26], f"{r['shadow']['model']} {r['shadow']['effort']}"[:24], r["runs"],
                         r["rounds"], r["misses"], r["extras"], r["failed"], state))
    print("Promotion stays manual: a /evolve change to skills/_shared/models.json, with the owner's approval.")
    return 0


def main(argv):
    if not argv or argv[0] not in ("compare", "summary"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if argv[0] == "summary":
        return cmd_summary(argv[1:])
    rest = argv[1:]
    as_json = "--json" in rest
    rest = [a for a in rest if a != "--json"]
    at = rest.index("--role") if "--role" in rest else -1
    role = rest[at + 1] if 0 <= at < len(rest) - 1 else None
    files = [a for i, a in enumerate(rest) if i not in (at, at + 1)] if role else []
    if not role or role.startswith("-") or len(files) != 2 or any(a.startswith("-") for a in files):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    res, code = compare_files(files[0], files[1], role)
    if as_json:
        print(json.dumps(res, indent=2))
    elif code:
        print(f"shadow_diff: {res['error']}", file=sys.stderr)
    else:
        print_compare(res)
    return code


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
