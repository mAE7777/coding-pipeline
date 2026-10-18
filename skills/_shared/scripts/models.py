#!/usr/bin/env python3
"""Which model and effort each pipeline role runs on: the routing table, its override, and its checks.

Usage:
  models.py resolve <route> [--json]   the model and effort one route runs on, and where each comes from
  models.py list [--json]              every route, resolved, and the shadow beside it when one is set
  models.py check [<file>]             check the routing table and the personal override file (its shadows
                                       included), or one file (a full table, or an override checked against
                                       the table)

The table is skills/_shared/models.json, in the folder above this script (the installed copy when run from
~/.claude). A route is a checker role, or <role>.<mode> for a role whose modes differ in what they judge:
  code-verifier.review | .reverify | .demo, cold-reader.documents | .reread | .understanding | .extract |
  .fidelity | .refidelity, loyal-evaluator, gate-judge, claim-verifier, change-reviewer, probe, and the
  builder-side routes (explorer, delegate, architect-runner, explain, scout-map).
run_isolated.py derives a checker's route from its role and mode (route_for) unless --route names one.

Each route has a model and an effort, and may carry a note:
  model   "default": no --model flag, so the Claude Code default serves (today's behavior);
          "session": a builder-side route, spawned from the session; the skill text decides;
          or a full model ID from allowed_models (never an alias that can move).
  effort  low, medium, high, xhigh, max, or inherit (a builder-side route takes the session's).
A checker route (an isolated run) never takes model session or effort inherit: check and every lookup refuse
them there, since every run on such a route would end ERROR.
"escalate" names the model and effort a gate retry moves to (gate_run.py), when the first attempt ended ERROR
or INCONCLUSIVE on another model or a lower effort.

Override: ~/.claude/.pipeline-models.json, {"routes": {"<route>": {"model": ..., "effort": ...}}}, for some
routes and some fields; the rest come from the table. PIPELINE_MODELS_IGNORE_OVERRIDE=1 ignores it (the
/evolve benchmarks measure the repository's own table).

Shadow: the same file may hold {"shadow": {"<route>": {"model": ..., "effort": ...}}} beside "routes": a candidate
setting that runs beside the route's own on real work (run_isolated.py runs it after the main run, and only the
main run's result counts; shadow_diff.py compares the two and says when a candidate is ready to promote, plan 7.3
step 4). A shadow names both fields: a model ID from allowed_models (never default or session) and an effort level
(never inherit). Only checker routes can have one; builder-side routes cannot. The ignore variable ignores the
shadows too. list and check show them.

Nothing falls back silently: an unknown route, a model outside allowed_models, any ID containing fable or
mythos, an unknown effort, or a malformed file is an error that names the route and the file, and every
lookup fails until it is fixed.
Exit 0 on success, 1 on an invalid entry or an unknown route, 2 on bad usage.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EFFORTS = ("low", "medium", "high", "xhigh", "max")
EFFORT_VALUES = EFFORTS + ("inherit",)
SPECIAL_MODELS = ("default", "session")
FORBIDDEN = ("fable", "mythos")
FULL_ID = re.compile(r"claude-[a-z0-9]+(-[a-z0-9]+)*")
# The routes run_isolated.py derives (route_for); the table must hold each one.
CHECKER_ROUTES = ("code-verifier.review", "code-verifier.reverify", "code-verifier.demo", "loyal-evaluator",
                  "gate-judge", "cold-reader.documents", "cold-reader.reread", "cold-reader.understanding",
                  "cold-reader.extract", "cold-reader.fidelity", "cold-reader.refidelity", "claim-verifier",
                  "change-reviewer", "probe")
# The block names an agent body's mode sections may use besides a route's own mode: the name the mode had
# before routes split it (a re-read is a documents read with --previous; a re-verify is a focused review).
MODE_ALIASES = {"reread": ("documents",), "refidelity": ("fidelity",), "reverify": ("review",),
                "extract": ("extraction",)}


class ModelsError(Exception):
    pass


def table_path(root=None):
    """The routing table: next to this script's folder, or <root>/skills/_shared/models.json for a tree."""
    return HERE.parent / "models.json" if root is None else Path(root) / "skills/_shared/models.json"


def override_path():
    return Path.home() / ".claude/.pipeline-models.json"


def override_ignored():
    return os.environ.get("PIPELINE_MODELS_IGNORE_OVERRIDE", "").strip().lower() in ("1", "true", "yes")


def read_json(path, what):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ModelsError(f"the {what} {path} is missing" +
                          ("; install.py apply installs it" if what == "routing table" else ""))
    except (OSError, ValueError) as exc:
        raise ModelsError(f"the {what} {path} cannot be read as JSON: {exc}")
    if not isinstance(data, dict):
        raise ModelsError(f"the {what} {path} is not a JSON object")
    return data


def model_problem(route, model, allowed, where):
    if not isinstance(model, str) or not model:
        return f"route {route} ({where}): model must be a non-empty string, not {model!r}"
    if any(f in model.lower() for f in FORBIDDEN):
        return f"route {route} ({where}): model {model} is a Fable or Mythos model, which the pipeline never routes to"
    if model in SPECIAL_MODELS or model in allowed:
        return None
    return (f"route {route} ({where}): model {model} is not allowed (use default, session, or one of "
            f"{', '.join(allowed) or 'no allowed models'})")


def effort_problem(route, effort, where):
    if effort in EFFORT_VALUES:
        return None
    return f"route {route} ({where}): effort {effort!r} is not one of {', '.join(EFFORT_VALUES)}"


def entry_problems(route, entry, allowed, where, partial=False):
    if not isinstance(entry, dict):
        return [f"route {route} ({where}): must be an object with model and effort"]
    out = []
    if route in CHECKER_ROUTES:
        if entry.get("model") == "session":
            out.append(f"route {route} ({where}): model session is for a builder-side route; a checker route runs "
                       "isolated and needs default or a model ID")
        if entry.get("effort") == "inherit":
            out.append(f"route {route} ({where}): effort inherit is for a builder-side route; a checker route runs "
                       f"isolated and needs an effort level ({', '.join(EFFORTS)})")
    extra = sorted(set(entry) - {"model", "effort", "note"})
    if extra:
        out.append(f"route {route} ({where}): unknown field(s) {', '.join(extra)}")
    if not partial:
        out += [f"route {route} ({where}): no {k}" for k in ("model", "effort") if k not in entry]
    elif "model" not in entry and "effort" not in entry:
        out.append(f"route {route} ({where}): sets neither model nor effort")
    if "model" in entry:
        out.append(model_problem(route, entry["model"], allowed, where))
    if "effort" in entry:
        out.append(effort_problem(route, entry["effort"], where))
    if "note" in entry and not isinstance(entry["note"], str):
        out.append(f"route {route} ({where}): note must be a string")
    return [p for p in out if p]


def table_problems(data, where):
    out = []
    if data.get("version") != 1:
        out.append(f"{where}: version must be 1, not {data.get('version')!r}")
    allowed = data.get("allowed_models")
    if not isinstance(allowed, list) or not allowed:
        out.append(f"{where}: allowed_models must be a non-empty list of full model IDs")
        allowed = []
    for m in allowed:
        if not isinstance(m, str) or any(f in m.lower() for f in FORBIDDEN):
            out.append(f"{where}: allowed_models holds {m!r}: a Fable or Mythos model is never allowed"
                       if isinstance(m, str) else f"{where}: allowed_models holds {m!r}, not a model ID")
        elif not FULL_ID.fullmatch(m) or not re.search(r"\d", m):
            out.append(f"{where}: allowed_models holds {m}, which is not a full model ID (claude-<family>-<version>)")
    allowed = [m for m in allowed if isinstance(m, str)]
    esc = data.get("escalate")
    if not isinstance(esc, dict):
        out.append(f"{where}: escalate must be an object with model and effort")
    else:
        if esc.get("model") not in allowed:
            out.append(f"{where}: escalate model {esc.get('model')!r} must be one of allowed_models")
        if esc.get("effort") not in EFFORTS:
            out.append(f"{where}: escalate effort {esc.get('effort')!r} must be one of {', '.join(EFFORTS)}")
    routes = data.get("routes")
    if not isinstance(routes, dict) or not routes:
        out.append(f"{where}: routes must be a non-empty object")
        routes = {}
    for route, entry in routes.items():
        out += entry_problems(route, entry, allowed, where)
    extra = sorted(set(data) - {"version", "allowed_models", "escalate", "routes", "note"})
    if extra:
        out.append(f"{where}: unknown field(s) {', '.join(extra)}")
    return out


def override_problems(data, table, where):
    out = []
    routes = data.get("routes", {})
    if not isinstance(routes, dict):
        return [f"{where}: routes must be an object of route: {{model, effort}}"]
    known = table.get("routes") or {}
    allowed = [m for m in table.get("allowed_models") or [] if isinstance(m, str)]
    for route, entry in routes.items():
        if route not in known:
            out.append(f"route {route} ({where}): unknown route (known: {', '.join(known)})")
            continue
        out += entry_problems(route, entry, allowed, where, partial=True)
    if "shadow" in data:
        out += shadow_problems(data["shadow"], table, where)
    extra = sorted(set(data) - {"version", "routes", "shadow", "note"})
    if extra:
        out.append(f"{where}: unknown field(s) {', '.join(extra)}")
    return out


def shadow_problems(shadow, table, where):
    """The problems of a shadow section: each route a known checker route, each entry a full setting."""
    if not isinstance(shadow, dict):
        return [f"{where}: shadow must be an object of route: {{model, effort}}"]
    known = table.get("routes") or {}
    allowed = [m for m in table.get("allowed_models") or [] if isinstance(m, str)]
    out = []
    for route, entry in shadow.items():
        if route not in known:
            out.append(f"shadow {route} ({where}): unknown route (known: {', '.join(known)})")
        elif route not in CHECKER_ROUTES:
            out.append(f"shadow {route} ({where}): {route} is a builder-side route, which cannot be shadowed "
                       "(a shadow runs beside an isolated checker run)")
        elif not isinstance(entry, dict):
            out.append(f"shadow {route} ({where}): must be an object with model and effort")
        else:
            out += shadow_entry_problems(route, entry, allowed, where)
    return out


def shadow_entry_problems(route, entry, allowed, where):
    """A shadow names a full model ID and an effort level: never default, session, or inherit."""
    out = []
    extra = sorted(set(entry) - {"model", "effort", "note"})
    if extra:
        out.append(f"shadow {route} ({where}): unknown field(s) {', '.join(extra)}")
    out += [f"shadow {route} ({where}): no {k}" for k in ("model", "effort") if k not in entry]
    if "model" in entry:
        model, problem = entry["model"], model_problem(route, entry["model"], allowed, where)
        if model in SPECIAL_MODELS:
            out.append(f"shadow {route} ({where}): model {model} is not a model ID; a shadow names the full model "
                       f"ID it runs on (one of {', '.join(allowed)})")
        elif problem and "not allowed" in problem:
            out.append(f"shadow {route} ({where}): model {model} is not allowed (use one of {', '.join(allowed)})")
        elif problem:
            out.append(problem.replace(f"route {route} (", f"shadow {route} (", 1))
    if "effort" in entry and entry["effort"] not in EFFORTS:
        out.append(f"shadow {route} ({where}): effort {entry['effort']!r} is not one of {', '.join(EFFORTS)}")
    if "note" in entry and not isinstance(entry["note"], str):
        out.append(f"shadow {route} ({where}): note must be a string")
    return [p for p in out if p]


def load(root=None, ignore_override=None):
    """The table and the override in force (None when absent or ignored), both checked; any problem raises."""
    path = table_path(root)
    table = read_json(path, "routing table")
    problems = table_problems(table, str(path))
    if problems:
        raise ModelsError("; ".join(problems))
    ignore = override_ignored() if ignore_override is None else ignore_override
    over, opath = None, override_path()
    if not ignore and opath.exists():
        over = read_json(opath, "personal override file")
        problems = override_problems(over, table, str(opath))
        if problems:
            raise ModelsError("; ".join(problems))
    return table, over, path, (opath if over is not None else None)


def resolve(route, root=None, ignore_override=None):
    """{route, model, effort, source (repo | override), escalate, note} for one route; ModelsError otherwise."""
    return pick(route, *load(root, ignore_override))


def pick(route, table, over, path, opath):
    routes = table["routes"]
    if route not in routes:
        raise ModelsError(f"unknown route {route!r} (known: {', '.join(routes)}; table {path})")
    entry = dict(routes[route])
    out = {"route": route, "model": entry["model"], "effort": entry["effort"], "source": "repo",
           "escalate": dict(table["escalate"]), "note": entry.get("note"), "table": str(path)}
    mine = ((over or {}).get("routes") or {}).get(route)
    if mine:
        fields = [k for k in ("model", "effort") if k in mine]
        out.update({k: mine[k] for k in fields})
        out.update({"source": "override", "override_file": str(opath), "override_fields": fields})
    return out


def choose(route, model=None, effort=None, root=None, ignore_override=None):
    """What one isolated checker run uses: an explicit model or effort over the route's, each checked, with its
    source (repo, override, or flag). A builder-side value (model session, effort inherit) is refused there."""
    table, over, path, opath = load(root, ignore_override)
    r = pick(route, table, over, path, opath)
    fields = r.get("override_fields") or []
    out = {"route": route, "model": r["model"], "effort": r["effort"],
           "model_source": "override" if "model" in fields else "repo",
           "effort_source": "override" if "effort" in fields else "repo", "escalate": r["escalate"]}
    if model is not None:
        problem = model_problem(route, model, table["allowed_models"], "the --model flag")
        if problem:
            raise ModelsError(problem)
        out.update(model=model, model_source="flag")
    if effort is not None:
        problem = effort_problem(route, effort, "the --effort flag")
        if problem:
            raise ModelsError(problem)
        out.update(effort=effort, effort_source="flag")
    if out["model"] == "session" or out["effort"] == "inherit":
        raise ModelsError(f"route {route} runs on model {out['model']} at effort {out['effort']}, which only a "
                          "builder-side helper can: an isolated run needs default or a model ID, and an effort level")
    return out


def shadow_entry(route, over, opath):
    """The override's shadow setting for one route (load has checked it), or None."""
    entry = ((over or {}).get("shadow") or {}).get(route)
    if not entry:
        return None
    return {"route": route, "model": entry["model"], "effort": entry["effort"], "source": "override",
            "override_file": str(opath), **({"note": entry["note"]} if entry.get("note") else {})}


def shadow(route, root=None, ignore_override=None):
    """The personal override's shadow setting for one route, or None; ModelsError when the files are invalid."""
    table, over, path, opath = load(root, ignore_override)
    return shadow_entry(route, over, opath)


def shadow_choice(route, flag=None, root=None, ignore_override=None):
    """The shadow beside one isolated run: the --shadow flag (<model>:<effort>) over the override's entry, or None.
    The flag is held to the override's rules; any problem raises ModelsError."""
    table, over, path, opath = load(root, ignore_override)
    if flag is None:
        return shadow_entry(route, over, opath)
    model, sep, effort = str(flag).partition(":")
    if not sep:
        raise ModelsError(f"the --shadow flag takes <model>:<effort>, not {flag!r}")
    problems = shadow_problems({route: {"model": model, "effort": effort}}, table, "the --shadow flag")
    if problems:
        raise ModelsError("; ".join(problems))
    return {"route": route, "model": model, "effort": effort, "source": "flag"}


def route_for(role, mode=None, previous=False, inputs=None):
    """The route of one checker run, from its role and how its pack is rendered (render_pack's precedence)."""
    inputs = inputs or []
    if role == "cold-reader":
        if "understanding" in inputs:
            return "cold-reader.understanding"
        if mode == "extract":
            return "cold-reader.extract"
        if mode == "fidelity":
            return "cold-reader.refidelity" if previous else "cold-reader.fidelity"
        return "cold-reader.reread" if previous else "cold-reader.documents"
    if role == "code-verifier":
        if mode == "demo":
            return "code-verifier.demo"
        if mode == "reverify":
            return "code-verifier.reverify"
        return "code-verifier.review"
    return role


def section_names(route):
    """The mode-section names an agent body keeps for this route: its mode and that mode's earlier name."""
    if "." not in route:
        return set()
    mode = route.split(".", 1)[1]
    return {mode, *MODE_ALIASES.get(mode, ())}


def escalation(model, effort, escalate):
    """Why a retry moves to the escalate model and effort, or None when the first attempt already ran there.
    The CLI default model at the escalate effort or above is today's setting, so it is not moved."""
    why = []
    if model not in SPECIAL_MODELS and model != escalate["model"]:
        why.append(f"model {model} is not {escalate['model']}")
    if effort in EFFORTS and EFFORTS.index(effort) < EFFORTS.index(escalate["effort"]):
        why.append(f"effort {effort} is below {escalate['effort']}")
    return "; ".join(why) or None


def describe(r):
    model = r["model"]
    said = {"default": "default (no --model flag; the Claude Code default serves)",
            "session": "session (spawned from the session; the skill text decides)"}.get(model, model)
    src = f"the personal override ({', '.join(r['override_fields'])})" if r["source"] == "override" \
        else "the repository table"
    return f"{r['route']}: model {said}, effort {r['effort']}, from {src}"


def describe_shadow(s):
    return (f"  shadow: {s['model']} {s['effort']} runs beside it on real work (only the routed run counts; "
            f"from {'the --shadow flag' if s['source'] == 'flag' else 'the personal override'})")


def shadow_lines(data):
    """One line per shadow an override file names (the well-formed ones; check prints the problems)."""
    shadow = data.get("shadow") if isinstance(data, dict) else None
    return [f"shadow {route}: {e.get('model')} {e.get('effort')} beside the routed setting"
            for route, e in (shadow.items() if isinstance(shadow, dict) else []) if isinstance(e, dict)]


def cmd_check(args):
    problems, shadows = [], []
    if args:
        path = Path(args[0])
        try:
            data = read_json(path, "file")
        except ModelsError as exc:
            print(f"FAIL {exc}")
            return 1
        if "allowed_models" in data:
            problems = table_problems(data, str(path))
            problems += [f"{path}: route {r} is derived by run_isolated.py but missing" for r in CHECKER_ROUTES
                         if r not in (data.get("routes") or {})]
            what = f"{len(data.get('routes') or {})} routes"
        else:
            try:
                table = read_json(table_path(), "routing table")
            except ModelsError as exc:
                print(f"FAIL {exc}")
                return 1
            problems = override_problems(data, table, str(path))
            shadows = shadow_lines(data)
            what = f"override of {len(data.get('routes') or {})} route(s) and {len(shadows)} shadow(s), checked " \
                   f"against {table_path()}"
    else:
        path = table_path()
        try:
            table = read_json(path, "routing table")
        except ModelsError as exc:
            print(f"FAIL {exc}")
            return 1
        problems = table_problems(table, str(path))
        problems += [f"{path}: route {r} is derived by run_isolated.py but missing" for r in CHECKER_ROUTES
                     if r not in (table.get("routes") or {})]
        opath = override_path()
        if override_ignored():
            state = "override ignored, shadows included (PIPELINE_MODELS_IGNORE_OVERRIDE)"
        elif opath.exists():
            try:
                over = read_json(opath, "personal override file")
                problems += override_problems(over, table, str(opath))
                shadows = shadow_lines(over)
            except ModelsError as exc:
                problems.append(str(exc))
            state = f"override {opath} checked" + (f", {len(shadows)} shadow(s)" if shadows else "")
        else:
            state = "no personal override"
        what = f"{len(table.get('routes') or {})} routes, {state}"
    for p in problems:
        print(f"FAIL {p}")
    for s in shadows:
        print(s)
    print(f"models: {'FAIL' if problems else 'OK'} ({what})")
    return 1 if problems else 0


def main(argv):
    if not argv or argv[0] not in ("resolve", "list", "check"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    sub, rest = argv[0], argv[1:]
    as_json = "--json" in rest
    rest = [a for a in rest if a != "--json"]
    if sub == "check":
        if len(rest) > 1 or as_json or any(a.startswith("-") for a in rest):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        return cmd_check(rest)
    if (sub == "resolve" and len(rest) != 1) or (sub == "list" and rest):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        if sub == "resolve":
            r = resolve(rest[0])
            print(json.dumps(r, indent=2) if as_json else describe(r))
            return 0
        loaded = load()
        table, path, opath = loaded[0], loaded[2], loaded[3]
        rows = [pick(route, *loaded) for route in table["routes"]]
        shadows = {r["route"]: shadow_entry(r["route"], loaded[1], opath) for r in rows}
    except ModelsError as exc:
        print(f"models: {exc}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps({"table": str(path), "override": str(opath) if opath else None,
                          "override_ignored": override_ignored(), "escalate": table["escalate"],
                          "routes": {r["route"]: r for r in rows},
                          "shadows": {k: v for k, v in shadows.items() if v}}, indent=2))
    else:
        for r in rows:
            print(describe(r))
            if shadows.get(r["route"]):
                print(describe_shadow(shadows[r["route"]]))
        print(f"escalate: {table['escalate']['model']} {table['escalate']['effort']}; table {path}; "
              + (f"override {opath}" if opath else "override ignored" if override_ignored() else "no personal override"))
    return 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
