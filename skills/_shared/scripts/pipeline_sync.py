#!/usr/bin/env python3
"""Update the installed pipeline from its repository in one command, and tell every open session when the skill
text it already read is out of date. The fast workflow (its manifest ~/.claude/.pipeline-fast-install.json) is
updated and watched the same way when it is installed. Nothing here pulls or installs in the background.

Usage:
  pipeline_sync.py update [--no-pull] [--json]   pull the repository, install it, register its hooks; then fast
  pipeline_sync.py status [--json]               what is installed, what the repositories hold, runs in progress
  pipeline_sync.py session-start                 SessionStart hook (matcher startup|resume|clear|fork)
  pipeline_sync.py prompt                        UserPromptSubmit hook

update. The repository is the install manifest's "repo" (~/.claude/.pipeline-install.json, written by install.py
apply). It refuses, exit 1 with the reason and what to do, when there is no manifest, no repository there, or it
is not a git work tree; when the work tree has uncommitted changes to tracked files, or untracked files under
skills/, agents/, or hooks/ (an /evolve edit in progress is never installed half-done; the private/ overlay is
never committed, so its files do not count); and when a pipeline run is in progress (below). Unless --no-pull:
when the current branch has an upstream, it is fetched (60 s at most; a failed fetch is reported and the update
goes on with the local HEAD) and fast-forwarded only when the branch is strictly behind; a diverged branch is
reported and never merged. Then, when the manifest's revision is HEAD and `install.py check` passes, it prints
"current". Otherwise it runs, from the repository, `install.py apply` (which keeps backups and refuses over live
edits under ~/.claude), `settings_patch.py --apply` (hooks are registered only after their scripts are
installed), and `install.py check`, and prints the revision before and after, the commits between them (at most
15), and which skills, agents, hooks, and shared files changed (the manifest's file hashes before and after). An
apply that did not install, a failed settings patch, or a failing check exits 1 with their own messages. Every
result is written to ~/.claude/.pipeline-sync.json (time, before, after, result, changed, and the history of
installs), which the prompt hook reads to name what changed without running git. One update runs at a time.

The fast workflow, after the pipeline's own update or its refusal (one part's refusal never stops the other):
when the fast manifest exists and names its repository ("repo"), update runs `install.py update --json` there
(with --no-pull when given; it refuses, pulls, and installs by the same rules) and reports it on its own lines:
"fast: current", "fast: updated <before> -> <after> (<n> commits)" with the commits, or "fast: refused: <reason>;
<what to do>". A manifest without "repo" was written by an older fast install.py: "fast: installed by an older
version; run python3 install.py apply once in the fast repository". The fast result is recorded under "fast" in
~/.claude/.pipeline-sync.json. update exits 1 when either part was refused or failed.

status. The installed revision and time, the repository's HEAD and branch, how far it is ahead of or behind its
upstream as of the last fetch (no network), uncommitted changes, the last update, and runs in progress; and for
the fast workflow when installed, its revision, time, repository, and commits there not installed.

Runs in progress. gate_run.py and run_isolated.py write ~/.claude/.pipeline-runs/<pid>.json ({pid, script,
project, started}) when they start and remove it when they end (a run stopped by a signal too). update counts an
entry whose process is alive and still runs that script as busy, and removes the others.

session-start (SessionStart). Records the revisions installed now (the pipeline's and fast's) for this session in
~/.claude/.pipeline-sessions/<session_id>.json (a resumed or forked session keeps the revisions it already has on
record, since its conversation holds the text it read then), and when a repository's local HEAD (no network)
is not its installed revision, prints a message for the owner: "The pipeline repository has <n> commit(s) not
installed (<before>..<after>). Type /pipeline update." (the fast workflow's repository likewise, in the same
message). Records older than 14 days are removed.

prompt (UserPromptSubmit). Three small file reads, no git, no network. When a manifest's revision differs from
the one recorded for this session, it adds a notice to the session's context once: the skill text read earlier
in the session is out of date, re-read the SKILL.md of the skill in use (or invoke it again) and the references
the next step relies on; with the skills and shared references that changed when the update history reaches
back to the session's revision. The notice speaks of the fast skills when only fast's revision changed, and of
both when both did. Then the new revisions are recorded for the session. A session with no record (started
before this hook existed) records the current revisions silently, and a record without fast's revision (written
before fast was watched) records fast's silently; so does a fast install that appears after the session began. A
short fast revision (an older fast install.py's) and the full sha it starts are one revision, never a change.

The hooks never block and never fail a session: an internal error becomes a one-line message, or nothing.
Exit 0 on success (and always for the hooks), 1 when update refused or failed, 2 on bad usage.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

LOG_LINES = 15
FETCH_TIMEOUT = 60
SESSION_DAYS = 14
HISTORY = 20
# The paths install.py installs from; the private/ overlay is local by design and never committed.
INSTALLED_FROM = ("skills/", "agents/", "hooks/")
SUFFIX = "+local-changes"  # install.py's revision for a work tree with changes
FAST_TIMEOUT = 600  # fast's install.py update: one fetch (60 s at most) and a copy of its skills
FAST_REAPPLY = "run python3 install.py apply once in the fast repository"
FAST_RESULTS = ("current", "updated", "refused", "failed")
SESSION_START_SECONDS = 8  # every git call of the SessionStart hook together (it is registered with 10 s)


def claude_dir():
    return Path.home() / ".claude"


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path):
    """The JSON object in path, or None when it is missing, unreadable, or not an object."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path, data):
    """Write through a temporary file and a rename, so a reader never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def describe_update(lu):
    """One recorded update for status: what happened, when, the revisions it moved between (an update) or stayed
    at (current), and the reason of a refusal or failure."""
    result = lu.get("result")
    revs = (f" ({short(lu.get('before'))} -> {short(lu.get('after'))})" if result == "updated"
            else f" ({short(lu.get('after'))})" if result == "current" and lu.get("after") else "")
    return f"{result} at {lu.get('time')}{revs}" + (f": {lu['reason']}" if lu.get("reason") else "")


def short(rev):
    if not rev:
        return "unknown"
    rev = str(rev)
    base, plus, rest = rev.partition("+")
    return (base[:7] if re.fullmatch(r"[0-9a-f]{40}", base) else base) + plus + rest


def plain(rev):
    """The commit a manifest revision names, without install.py's local-changes mark."""
    rev = str(rev or "")
    return rev[:-len(SUFFIX)] if rev.endswith(SUFFIX) else rev


def same_revision(a, b):
    """True when two revisions name one commit: equal, or one is the short sha (7 to 39 hex characters) of the
    other's full one. An older fast install.py recorded the short sha, and its first update records the full one
    of the same commit, which is no change."""
    a, b = plain(a), plain(b)
    if not a or not b or a == b:
        return bool(a) and a == b
    s, full = sorted((a, b), key=len)
    return (re.fullmatch(r"[0-9a-f]{7,39}", s) is not None and re.fullmatch(r"[0-9a-f]{40}", full) is not None
            and full.startswith(s))


def git(repo, *args, timeout=30):
    """(exit code, stdout, stderr) of git in repo; exit code None when git could not run or ran out of time."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except FileNotFoundError:
        return None, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return None, "", f"git {args[0]} did not finish within {timeout} s"
    except OSError as exc:
        return None, "", f"git could not run: {exc}"
    return r.returncode, r.stdout.rstrip(), r.stderr.strip()  # a porcelain line may start with a space


# ---------------------------------------------------------------- runs in progress


def runs_dir():
    return claude_dir() / ".pipeline-runs"


def register_run(script, project=None):
    """Write this process's entry in the run registry; returns its path, or None. Never raises: the registry tells
    /pipeline update to wait, and is never a reason for a run to fail."""
    try:
        if project:
            project = str(Path(project).resolve())
        path = runs_dir() / f"{os.getpid()}.json"
        write_json(path, {"pid": os.getpid(), "script": script, "project": project, "started": now()})
        return path
    except Exception:
        return None


def unregister_run(path):
    try:
        if path:
            Path(path).unlink()
    except Exception:
        pass


def process_runs(pid, script):
    """True when pid is alive and, where ps can tell, still runs script (a reused pid does not count)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except (OSError, OverflowError, ValueError):
        return False
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot tell more: the cautious answer is that it runs
    if r.returncode != 0:
        return False
    return not script or script in r.stdout


def live_runs(prune=False, skip_pid=None):
    """The registry's entries whose process still runs; with prune, the other entries are removed."""
    live = []
    try:
        entries = sorted(runs_dir().glob("*.json"))
    except OSError:
        return live
    for path in entries:
        rec = read_json(path) or {}
        try:
            pid = int(rec.get("pid") or path.stem)
        except (TypeError, ValueError):
            pid = None
        if pid is not None and pid == skip_pid:
            continue
        script = rec.get("script") if isinstance(rec.get("script"), str) else None
        if pid is not None and process_runs(pid, script):
            live.append({"pid": pid, "script": script or "?", "project": rec.get("project"),
                         "started": rec.get("started"), "entry": str(path)})
        elif prune:
            try:
                path.unlink()
            except OSError:
                pass
    return live


def describe_runs(runs):
    return "; ".join(f"{r['script']} (pid {r['pid']}" + (f", {r['project']}" if r.get("project") else "")
                     + (f", started {r['started']}" if r.get("started") else "") + ")" for r in runs)


# ---------------------------------------------------------------- update


def manifest_path():
    return claude_dir() / ".pipeline-install.json"


def sync_path():
    return claude_dir() / ".pipeline-sync.json"


def fast_manifest_path():
    return claude_dir() / ".pipeline-fast-install.json"


def fast_revision():
    """The fast workflow's installed revision, or None when it is not installed or its manifest is unreadable."""
    rev = (read_json(fast_manifest_path()) or {}).get("revision")
    return rev if isinstance(rev, str) and rev else None


def changed_parts(before, after):
    """What differs between two manifests' file hashes, grouped the way an owner thinks of the install."""
    claude = claude_dir()
    out = {"skills": set(), "skill_md": set(), "agents": set(), "hooks": set(), "shared": [], "other": []}
    for p in sorted(set(before) | set(after)):
        if before.get(p) == after.get(p):
            continue
        try:
            rel = Path(p).relative_to(claude).parts
        except ValueError:
            out["other"].append(p)
            continue
        if rel[:2] == ("skills", "_shared") and len(rel) > 2:
            out["shared"].append("/".join(rel[2:]))
        elif rel[:1] == ("skills",) and len(rel) > 2:
            out["skills"].add(rel[1])
            if rel[2:] == ("SKILL.md",):
                out["skill_md"].add(rel[1])
        elif rel[:1] == ("agents",) and len(rel) == 2:
            out["agents"].add(Path(rel[1]).stem)
        elif rel[:1] == ("hooks",) and len(rel) == 2:
            out["hooks"].add(rel[1])
        else:
            out["other"].append("/".join(rel))
    return {k: sorted(v) for k, v in out.items()}


def describe_changed(ch):
    parts = []
    for key, label in (("skills", "skills"), ("agents", "agents"), ("hooks", "hooks")):
        if ch.get(key):
            parts.append(f"{label} {', '.join(ch[key])}")
    for key, label in (("shared", "shared file(s)"), ("other", "other file(s)")):
        if ch.get(key):
            names = ch[key]
            parts.append(f"{len(names)} {label} ({', '.join(names[:6])}{' ...' if len(names) > 6 else ''})")
    return "; ".join(parts) or "no installed file"


def files_of(manifest):
    files = (manifest or {}).get("files")
    return files if isinstance(files, dict) else {}


def write_sync(result):
    """The update's result for the prompt hook and for status; installs also go into the history."""
    try:
        old = read_json(sync_path()) or {}
        history = [h for h in old.get("history") or [] if isinstance(h, dict)]
        if result.get("installed"):
            history.append({"time": now(), "before": result.get("before"), "after": result.get("after"),
                            "changed": result.get("changed")})
        fast = result.get("fast")
        write_json(sync_path(), {"time": now(), "before": result.get("before"), "after": result.get("after"),
                                 "result": result["result"], "reason": result.get("reason"),
                                 "changed": result.get("changed"), "history": history[-HISTORY:],
                                 "fast": None if fast is None else
                                 {"time": now(), **{k: fast.get(k) for k in ("result", "before", "after", "count",
                                                                             "reason", "todo")}}})
    except Exception as exc:
        result.setdefault("notes", []).append(f"could not write {sync_path()}: {exc}")


def tail(text, n=40):
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join(lines[-n:])


def refuse(result, reason, todo):
    result.update(result="refused", reason=reason, todo=todo)
    return 1


def pull(repo, result):
    """Fetch the upstream and fast-forward when strictly behind; every outcome goes into the notes."""
    notes = result["notes"]
    code, branch, _ = git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if code != 0 or not branch:
        notes.append("HEAD is detached, so there is no upstream to pull from; installing the local HEAD")
        return
    code, upstream, _ = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if code != 0 or not upstream:
        notes.append(f"the branch {branch} has no upstream, so nothing was pulled; installing the local HEAD")
        return
    code, _, err = git(repo, "fetch", "--quiet", timeout=FETCH_TIMEOUT)
    if code != 0:
        notes.append(f"fetching {upstream} failed ({tail(err, 2) or f'exit {code}'}); going on with the local HEAD")
    code, counts, _ = git(repo, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    try:
        ahead, behind = (int(x) for x in counts.split())
    except ValueError:
        notes.append(f"could not compare {branch} with {upstream}; nothing was merged")
        return
    if ahead and behind:
        notes.append(f"{branch} and {upstream} have diverged ({ahead} local and {behind} upstream commit(s)): nothing "
                     "was merged. Merge or rebase it yourself, then type /pipeline update again; installing the "
                     "local HEAD meanwhile")
    elif behind:
        code, _, err = git(repo, "merge", "--ff-only", "--quiet", "@{u}")
        if code == 0:
            notes.append(f"fast-forwarded {branch} by {behind} commit(s) from {upstream}")
        else:
            notes.append(f"could not fast-forward {branch} to {upstream} ({tail(err, 2) or f'exit {code}'}); "
                         "installing the local HEAD")
    elif ahead:
        notes.append(f"{branch} is {ahead} commit(s) ahead of {upstream} (not pushed); nothing to pull")
    else:
        notes.append(f"{branch} is even with {upstream}")


def commit_log(repo, before, after):
    """(lines, how many more) of the commits from before to after; None when before is not in the history."""
    code, count, _ = git(repo, "rev-list", "--count", f"{before}..{after}")
    if code != 0 or not count.isdigit():
        return None, 0
    code, log, _ = git(repo, "log", "--oneline", f"-n{LOG_LINES}", f"{before}..{after}")
    lines = log.splitlines() if code == 0 else []
    return lines, max(0, int(count) - len(lines))


def run_py(repo, script, *args):
    try:
        r = subprocess.run([sys.executable, str(repo / script), *args], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, cwd=str(repo))
    except OSError as exc:
        return 127, f"{script} could not start: {exc}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def manifest_stamp():
    """(mtime in ns, bytes) of the install manifest: whether install.py apply rewrote it."""
    try:
        return manifest_path().stat().st_mtime_ns, manifest_path().read_bytes()
    except OSError:
        return None


def fail_lines(*outputs):
    seen = []
    for out in outputs:
        for line in (out or "").splitlines():
            if line.startswith(("FAIL", "STOP")) and line not in seen:
                seen.append(line)
    return seen


def update(no_pull=False):
    result = {"result": None, "reason": None, "todo": None, "before": None, "after": None, "installed": False,
              "notes": [], "log": [], "log_more": 0, "changed": None, "repo": None, "fast": None}
    me = register_run("pipeline_sync.py update")  # one update at a time: a second one finds this entry
    try:
        code = _update(no_pull, result)
        try:  # whatever the pipeline's own part did
            result["fast"] = fast_update(no_pull)
        except Exception as exc:  # the pipeline's own result is still reported
            result["fast"] = {**fast_result(), "result": "failed", "reason": f"the fast part hit an internal error: "
                                                                             f"{exc.__class__.__name__}: {exc}"}
    finally:
        unregister_run(me)
    write_sync(result)
    fast = result["fast"]
    if fast is not None and fast["result"] not in ("current", "updated"):
        code = 1
    return code, result


def fast_result():
    return {"result": None, "before": None, "after": None, "commits": [], "count": 0, "notes": [], "reason": None,
            "todo": None, "repo": None, "older": False}


def fast_refused(out, reason, todo):
    out.update(result="refused", reason=reason, todo=todo)
    return out


def fast_update(no_pull):
    """The fast workflow's part of the update: None when it is not installed, else {result, before, after, commits,
    count, notes, reason, todo, repo, older, output}."""
    out = fast_result()
    path = fast_manifest_path()
    if not path.exists():
        return None
    manifest = read_json(path)
    if manifest is None:
        return fast_refused(out, f"the fast workflow's install manifest {path} is unreadable", FAST_REAPPLY)
    out["before"] = manifest.get("revision")
    repo = manifest.get("repo")
    if not isinstance(repo, str) or not repo:
        out["older"] = True  # written by a fast install.py from before update existed
        return fast_refused(out, "installed by an older version", FAST_REAPPLY)
    out["repo"] = repo
    repo = Path(repo)
    if not (repo / "install.py").is_file():
        return fast_refused(out, f"the fast workflow was installed from {repo}, which no longer holds its repository "
                                 "(no install.py there)", "clone the fast repository and " + FAST_REAPPLY)
    others = [r for r in live_runs(skip_pid=os.getpid()) if r["script"] == "pipeline_sync.py update"]
    if others:
        return fast_refused(out, "another /pipeline update is running: " + describe_runs(others),
                            "wait for it to finish, then type /pipeline update again")
    args = [sys.executable, str(repo / "install.py"), "update", "--home", str(Path.home()), "--json"]
    try:
        r = subprocess.run(args + (["--no-pull"] if no_pull else []), capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, cwd=str(repo), timeout=FAST_TIMEOUT)
    except subprocess.TimeoutExpired:
        out.update(result="failed", reason=f"the fast workflow's install.py update did not finish within "
                                            f"{FAST_TIMEOUT} s", todo=f"run python3 install.py update in {repo}")
        return out
    except OSError as exc:
        out.update(result="failed", reason=f"the fast workflow's install.py could not start: {exc}")
        return out
    got = last_json_object(r.stdout)
    if got is None or got.get("result") not in FAST_RESULTS:
        out.update(result="failed", reason=f"the fast workflow's install.py update gave no result this script can "
                                            f"read (exit {r.returncode}); its install.py may predate update --json",
                   todo=f"pull the fast repository at {repo}, then " + FAST_REAPPLY,
                   output=tail((r.stdout or "") + "\n" + (r.stderr or ""), 8))
        return out
    for k in ("before", "after", "reason", "todo"):
        if isinstance(got.get(k), str) and got[k]:
            out[k] = got[k]
    out["result"] = got["result"]
    out["commits"] = [c for c in got.get("commits") or [] if isinstance(c, str)]
    out["notes"] = [n for n in got.get("notes") or [] if isinstance(n, str)]
    if r.returncode != 0 and out["result"] in ("current", "updated"):
        out["notes"].append(f"install.py update said {out['result']} but exited {r.returncode}")
        out.update(result="failed", reason=f"the fast workflow's install.py update exited {r.returncode}")
    if out["result"] == "failed" and (r.stderr or "").strip():
        out["output"] = tail(r.stderr, 8)
    out["count"] = len(out["commits"])
    if out["result"] == "updated" and out["before"] and out["after"]:
        code, count, _ = git(repo, "rev-list", "--count", f"{plain(out['before'])}..{plain(out['after'])}")
        if code == 0 and count.isdigit() and int(count) >= out["count"]:
            out["count"] = int(count)  # the list stops at 15
    return out


def last_json_object(text):
    """The last JSON object printed in text (it may follow other lines), or None."""
    text = text or ""
    starts = [0] + [m.start() + 1 for m in re.finditer(r"\n\{", text)]
    for start in reversed(starts):
        try:
            got = json.loads(text[start:])
        except ValueError:
            continue
        if isinstance(got, dict):
            return got
    return None


def _update(no_pull, result):
    home = Path.home()
    bootstrap = ("install once from a clone of the pipeline repository: python3 install.py apply, then "
                 "python3 settings_patch.py --apply; from then on /pipeline update does both")
    manifest = read_json(manifest_path())
    if manifest is None:
        return refuse(result, f"there is no readable install manifest at {manifest_path()}", bootstrap)
    result["before"] = before = manifest.get("revision")
    repo = manifest.get("repo")
    if not isinstance(repo, str) or not repo:
        return refuse(result, f"the install manifest {manifest_path()} names no repository", bootstrap)
    repo = Path(repo)
    result["repo"] = str(repo)
    if not (repo / "install.py").is_file():
        return refuse(result, f"~/.claude was installed from {repo}, which no longer holds the pipeline repository "
                              "(no install.py there)", bootstrap)
    code, inside, err = git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0 or inside != "true":
        return refuse(result, f"{repo} is not a git work tree ({err or inside or 'git said no'}), so it cannot be "
                              "pulled", "clone the pipeline repository with git and " + bootstrap)
    code, dirty, _ = git(repo, "status", "--porcelain", "--untracked-files=no")
    if code != 0:
        return refuse(result, f"git status failed in {repo}", "run git status there and fix what it reports")
    if dirty:
        files = [line[3:] for line in dirty.splitlines()]
        return refuse(result, f"the repository {repo} has uncommitted changes to {len(files)} tracked file(s) ("
                              + ", ".join(files[:5]) + (" ..." if len(files) > 5 else "") + "); an edit in progress "
                              "is never installed half-done",
                      "finish the change and commit it (or discard it), then type /pipeline update again")
    code, untracked, _ = git(repo, "ls-files", "--others", "--exclude-standard", "--", *INSTALLED_FROM)
    if code != 0:
        return refuse(result, f"git ls-files failed in {repo}", "run git status there and fix what it reports")
    if untracked:
        files = untracked.splitlines()
        return refuse(result, f"the repository {repo} has {len(files)} untracked file(s) where install.py installs "
                              "from (" + ", ".join(files[:5]) + (" ..." if len(files) > 5 else "") + ")",
                      "commit them, or move them out of skills/, agents/, and hooks/, then type /pipeline update "
                      "again")
    runs = live_runs(prune=True, skip_pid=os.getpid())
    if runs:
        return refuse(result, "a pipeline run is in progress, and installing now would change the scripts under it: "
                              + describe_runs(runs),
                      "wait for it to finish (or stop it), then type /pipeline update again")
    if no_pull:
        result["notes"].append("not pulled (--no-pull); installing the local HEAD")
    else:
        pull(repo, result)
    code, head, err = git(repo, "rev-parse", "HEAD")
    if code != 0 or not head:
        return refuse(result, f"the repository {repo} has no commit to install ({err})", "commit the pipeline first")
    result["after"] = head
    if plain(before) == head:
        code, out = run_py(repo, "install.py", "check", "--home", str(home))
        if code == 0:
            result["result"] = "current"
            return 0
        result["notes"].append("install.py check failed, so the install ran again; the check said: "
                               + "; ".join(fail_lines(out)[:8]))
    stamp = manifest_stamp()
    code, out = run_py(repo, "install.py", "apply", "--home", str(home))
    after_manifest = read_json(manifest_path())
    installed = after_manifest is not None and manifest_stamp() != stamp \
        and plain(after_manifest.get("revision")) == head
    result["installed"] = installed
    if not installed:
        result.update(result="failed", reason=f"install.py apply did not install (exit {code}); this update changed "
                                              "nothing in ~/.claude", output=tail(out))
        return 1
    result["after"] = after_manifest.get("revision")
    result["changed"] = changed_parts(files_of(manifest), files_of(after_manifest))
    lines, more = commit_log(repo, plain(before), head)
    if lines is None:
        result["notes"].append(f"the installed revision {short(before)} is not in this repository's history, so "
                               "the commits between cannot be listed")
    else:
        result["log"], result["log_more"] = lines, more
    code, sout = run_py(repo, "settings_patch.py", "--apply", "--home", str(home))
    if code != 0:
        result.update(result="failed", reason=f"settings_patch.py --apply failed (exit {code}); the files are "
                                              "installed, but the hooks may not be registered", output=tail(sout))
        return 1
    code, cout = run_py(repo, "install.py", "check", "--home", str(home))
    if code != 0:
        result.update(result="failed", reason="the files are installed and the hooks registered, but install.py "
                                              "check fails", output="\n".join(fail_lines(out, cout)) or tail(cout))
        return 1
    result["result"] = "updated"
    return 0


def print_update(r):
    if r["result"] == "refused":
        print(f"update refused: {r['reason']}")
        print(f"What to do: {r['todo']}")
    elif r["result"] == "current":
        print(f"current: ~/.claude holds {short(r['after'])}, the repository's HEAD, and install.py check passes")
    elif r["result"] == "updated":
        print(f"updated: {short(r['before'])} -> {short(r['after'])}")
        if r["log"]:
            print("commits:")
            for line in r["log"]:
                print(f"  {line}")
            if r["log_more"]:
                print(f"  ... and {r['log_more']} more")
        print(f"changed: {describe_changed(r['changed'] or {})}")
        print("ran: install.py apply, settings_patch.py --apply, install.py check (passes)")
        print("Open sessions are told at their next prompt that the skill text they already read is out of date.")
    else:
        print(f"update failed: {r['reason']}")
        if r.get("installed"):
            print(f"installed: {short(r['before'])} -> {short(r['after'])}; changed: "
                  f"{describe_changed(r['changed'] or {})}; open sessions are told at their next prompt")
        elif r.get("before") or r.get("after"):
            print(f"revision: {short(r['before'])} installed; the repository is at {short(r['after'])}")
        if r.get("output"):
            print(r["output"])
    for note in r.get("notes") or []:
        print(f"note: {note}")
    print_fast_update(r.get("fast"))


def print_fast_update(f):
    """The fast workflow's part, on its own lines; nothing when fast is not installed."""
    if f is None:
        return
    if f.get("older"):
        print(f"fast: installed by an older version; {FAST_REAPPLY}")
    elif f["result"] == "current":
        print("fast: current")
    elif f["result"] == "updated":
        n = f.get("count") or len(f["commits"])
        print(f"fast: updated {short(f['before'])} -> {short(f['after'])} ({n} commit{'' if n == 1 else 's'})")
        for line in f["commits"]:
            print(f"  {line}")
        if n > len(f["commits"]) and f["commits"]:
            print(f"  ... and {n - len(f['commits'])} more")
    else:
        print(f"fast: {f['result']}: {f.get('reason') or 'no reason given'}" + (f"; {f['todo']}" if f.get("todo")
                                                                                 else ""))
        if f.get("output"):
            print(f["output"])
    for note in f.get("notes") or []:
        print(f"fast note: {note}")


# ---------------------------------------------------------------- status


def status():
    out = {"installed": None, "installed_at": None, "repo": None, "head": None, "branch": None, "upstream": None,
           "ahead": None, "behind": None, "not_installed": None, "uncommitted": None, "untracked": None,
           "runs": live_runs(), "last_update": None, "problems": []}
    manifest = read_json(manifest_path())
    if manifest is None:
        out["problems"].append(f"no readable install manifest at {manifest_path()} (install.py apply has not run)")
    else:
        out.update(installed=manifest.get("revision"), installed_at=manifest.get("installed"),
                   repo=manifest.get("repo"))
    sync = read_json(sync_path())
    if sync:
        out["last_update"] = {k: sync.get(k) for k in ("time", "result", "before", "after", "reason")}
    repo = Path(out["repo"]) if isinstance(out["repo"], str) and out["repo"] else None
    if repo is not None:
        code, head, err = git(repo, "rev-parse", "HEAD")
        if code != 0:
            out["problems"].append(f"{repo} is not a readable git repository ({err or 'git failed'})")
        else:
            out["head"] = head
            code, branch, _ = git(repo, "symbolic-ref", "--short", "-q", "HEAD")
            out["branch"] = branch if code == 0 else None
            code, upstream, _ = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
            if code == 0 and upstream:
                out["upstream"] = upstream
                code, counts, _ = git(repo, "rev-list", "--left-right", "--count", "HEAD...@{u}")
                if code == 0 and len(counts.split()) == 2:
                    out["ahead"], out["behind"] = (int(x) for x in counts.split())
            if plain(out["installed"]) != head:
                code, count, _ = git(repo, "rev-list", "--count", f"{plain(out['installed'])}..{head}")
                out["not_installed"] = int(count) if code == 0 and count.isdigit() else None
            code, dirty, _ = git(repo, "status", "--porcelain", "--untracked-files=no")
            out["uncommitted"] = len(dirty.splitlines()) if code == 0 else None
            code, untracked, _ = git(repo, "ls-files", "--others", "--exclude-standard", "--", *INSTALLED_FROM)
            out["untracked"] = len(untracked.splitlines()) if code == 0 else None
    out["fast"] = fast_status((sync or {}).get("fast"))
    return out


def fast_status(last_update):
    """The fast workflow's install as status shows it (no network), or None when it is not installed."""
    path = fast_manifest_path()
    if not path.exists():
        return None
    out = {"installed": None, "installed_at": None, "repo": None, "head": None, "ahead": None, "not_installed": None,
           "older": False, "last_update": last_update if isinstance(last_update, dict) else None, "problems": []}
    manifest = read_json(path)
    if manifest is None:
        out["problems"].append(f"the fast install manifest {path} is unreadable: {FAST_REAPPLY}")
        return out
    out.update(installed=manifest.get("revision"), installed_at=manifest.get("installed"))
    repo = manifest.get("repo")
    if not isinstance(repo, str) or not repo:
        out["older"] = True
        return out
    out["repo"] = repo
    code, head, err = git(repo, "rev-parse", "HEAD")
    if code != 0 or not head:
        out["problems"].append(f"the fast repository {repo} is not a readable git repository ({err or 'git failed'})")
        return out
    out["head"] = head
    out["ahead"] = not same_revision(out["installed"], head)
    if out["ahead"]:
        code, count, _ = git(repo, "rev-list", "--count", f"{plain(out['installed'])}..{head}")
        out["not_installed"] = int(count) if code == 0 and count.isdigit() else None
    return out


def print_status(s):
    print(f"installed: {short(s['installed'])}" + (f" at {s['installed_at']}" if s["installed_at"] else "")
          + (f" from {s['repo']}" if s["repo"] else ""))
    if s["head"]:
        line = f"repository: HEAD {short(s['head'])}" + (f" on {s['branch']}" if s["branch"] else " (detached)")
        if s["upstream"]:
            line += f"; {s['ahead']} ahead, {s['behind']} behind {s['upstream']} as of the last fetch"
        else:
            line += "; no upstream"
        print(line)
        if plain(s["installed"]) == s["head"]:
            print("the installed revision is the repository's HEAD")
        else:
            n = s["not_installed"]
            print((f"{n} commit(s) not installed" if n is not None else "HEAD is not the installed revision")
                  + ": type /pipeline update")
        print(f"uncommitted: {s['uncommitted']} tracked file(s) changed, {s['untracked']} untracked file(s) under "
              "skills/, agents/, hooks/")
    lu = s["last_update"]
    if lu:
        print(f"last update: {describe_update(lu)}")
    print(f"runs in progress: {describe_runs(s['runs']) if s['runs'] else 'none'}")
    for p in s["problems"]:
        print(f"problem: {p}")
    f = s.get("fast")
    if f is None:
        return
    print(f"fast: installed {short(f['installed'])}" + (f" at {f['installed_at']}" if f["installed_at"] else "")
          + (f" from {f['repo']}" if f["repo"] else ""))
    if f["older"]:
        print(f"fast: installed by an older version, which recorded no repository; {FAST_REAPPLY}")
    elif f["head"]:
        if not f["ahead"]:
            print(f"fast repository: HEAD {short(f['head'])}, the installed revision")
        else:
            n = f["not_installed"]
            print(f"fast repository: HEAD {short(f['head'])}; "
                  + (f"{n} commit(s) not installed" if n else "HEAD is not the installed revision")
                  + ": type /pipeline update")
    lu = f["last_update"]
    if lu:
        print(f"fast last update: {describe_update(lu)}")
    for p in f["problems"]:
        print(f"problem: {p}")


# ---------------------------------------------------------------- hooks


def sessions_dir():
    return claude_dir() / ".pipeline-sessions"


def session_file(data):
    sid = data.get("session_id") if isinstance(data, dict) else None
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", sid) or sid.startswith("."):
        return None
    return sessions_dir() / f"{sid}.json"


def read_hook_input():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def installed_revision():
    rev = (read_json(manifest_path()) or {}).get("revision")
    return rev if isinstance(rev, str) and rev else None


def session_start():
    data = read_hook_input()
    manifest = read_json(manifest_path())
    fast = read_json(fast_manifest_path())
    if manifest is None and fast is None:
        return None
    rev = (manifest or {}).get("revision")
    fast_rev = (fast or {}).get("revision")
    rev, fast_rev = (r if isinstance(r, str) and r else None for r in (rev, fast_rev))
    path = session_file(data)
    if path is not None and (rev or fast_rev):
        rec = read_json(path)
        # A resumed or forked conversation still holds the text it read before: its record stays.
        keep = data.get("source") in ("resume", "fork") and rec and (isinstance(rec.get("revision"), str)
                                                                     or isinstance(rec.get("fast_revision"), str))
        if not keep:
            try:
                write_json(path, {"revision": rev, "fast_revision": fast_rev, "recorded": now()})
            except OSError:
                pass  # the prompt hook records it later
    cutoff = time.time() - SESSION_DAYS * 86400
    for old in sessions_dir().iterdir() if sessions_dir().is_dir() else []:  # a stray temporary file too
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    deadline = time.monotonic() + SESSION_START_SECONDS
    found = [line for line in (not_installed("The pipeline repository", (manifest or {}).get("repo"), rev, deadline),
                               not_installed("The fast workflow's repository", (fast or {}).get("repo"), fast_rev,
                                             deadline)) if line]
    return " ".join(found) + " Type /pipeline update." if found else None


def not_installed(label, repo, rev, deadline):
    """The sentence naming what repo's local HEAD holds beyond the installed revision rev, or None (no network)."""
    if not isinstance(repo, str) or not repo or not rev or not Path(repo).is_dir():
        return None
    code, head, _ = git(repo, "rev-parse", "HEAD", timeout=max(0.5, min(5, deadline - time.monotonic())))
    if code != 0 or not head or same_revision(rev, head):
        return None
    code, count, _ = git(repo, "rev-list", "--count", f"{plain(rev)}..{head}",
                         timeout=max(0.5, min(5, deadline - time.monotonic())))
    if code == 0 and count.isdigit() and int(count) > 0:
        return f"{label} has {count} commit(s) not installed ({short(plain(rev))}..{short(head)})."
    return f"{label}'s HEAD ({short(head)}) is not the revision installed in ~/.claude ({short(rev)})."


def changed_since(since, current):
    """{skills, skill_md, references} changed between two installed revisions, from the update history; None when
    the history does not reach back to since (an install by hand, or an old history)."""
    sync = read_json(sync_path()) or {}
    history = [h for h in sync.get("history") or [] if isinstance(h, dict)]
    found = {"skills": set(), "skill_md": set(), "references": set()}
    cur = current
    for h in reversed(history):
        if cur == since:
            break
        if h.get("after") != cur:
            continue
        ch = h.get("changed") if isinstance(h.get("changed"), dict) else {}
        names = {k: [x for x in ch.get(k) if isinstance(x, str)] if isinstance(ch.get(k), list) else []
                 for k in ("skills", "skill_md", "shared")}
        found["skills"].update(names["skills"])
        found["skill_md"].update(names["skill_md"])
        found["references"].update(x[len("references/"):] for x in names["shared"] if x.startswith("references/"))
        cur = h.get("before")
    return {k: sorted(v) for k, v in found.items()} if cur == since else None


def notice(before, after, fast=None):
    """The out-of-date notice: the pipeline's when before and after are given, the fast workflow's when fast is
    (before, after), both in one text when both changed."""
    if before is None:
        return (f"The fast skills in ~/.claude were updated ({short(fast[0])} -> {short(fast[1])}) after this session "
                "read their instructions. Fast skill text you read earlier in this session is out of date: before the "
                "next step, re-read the SKILL.md of the fast skill in use (~/.claude/skills/<name>-fast/SKILL.md). "
                "fast.py already runs the new version. If this session has used no fast skill, nothing needs doing.")
    text = pipeline_notice(before, after)
    if fast is None:
        return text + " If this session has used no pipeline skill, nothing needs doing."
    return (text + f" The fast skills were updated too ({short(fast[0])} -> {short(fast[1])}): re-read the SKILL.md "
                   "of a fast skill in use as well (~/.claude/skills/<name>-fast/SKILL.md). If this session has used "
                   "neither pipeline's skills, nothing needs doing.")


def pipeline_notice(before, after):
    text = (f"The coding pipeline in ~/.claude was updated ({short(before)} -> {short(after)}) after this session read "
            "its instructions. Skill text you read earlier in this session is out of date: before the next pipeline "
            "step, re-read the SKILL.md of the skill in use (~/.claude/skills/<name>/SKILL.md) and any reference that "
            "step relies on. Scripts, hooks, and checker agents already run the new version.")
    ch = changed_since(before, after)
    if ch is not None:
        text += (f" Skills changed: {', '.join(ch['skills'])}." if ch["skills"] else
                 " No skill's own files changed.")
        if ch["references"]:
            text += f" Shared references changed: {', '.join(ch['references'])}."
    if ch is None or ch["skill_md"]:
        text += (" A skill's own hooks (its SKILL.md frontmatter) are registered when it is invoked, so for a skill "
                 "whose SKILL.md changed, invoke it again (for example /dev resume) rather than only re-reading it.")
    return text


def prompt():
    data = read_hook_input()
    path = session_file(data)
    if path is None:
        return None
    rev, fast_rev = installed_revision(), fast_revision()
    if rev is None and fast_rev is None:
        return None
    rec = read_json(path)
    recorded = rec.get("revision") if rec else None
    recorded_fast = rec.get("fast_revision") if rec else None
    has_fast = rec is not None and "fast_revision" in rec  # an older record has no fast field: recorded silently
    same_fast = fast_rev is None or recorded_fast == fast_rev or same_revision(recorded_fast, fast_rev)
    if (rev is None or recorded == rev) and has_fast and same_fast:
        try:
            if path.stat().st_mtime < time.time() - 86400:
                os.utime(path)  # a session still open is never pruned as old
        except OSError:
            pass
        return None
    # No record (started before this hook) or a revision not recorded as text (none installed then): silently.
    full = rev is not None and isinstance(recorded, str) and recorded != rev
    fast = fast_rev is not None and isinstance(recorded_fast, str) and not same_fast
    text = notice(recorded if full else None, rev, (recorded_fast, fast_rev) if fast else None) \
        if full or fast else None
    try:  # an unreadable manifest (None) keeps what was recorded, so its next change is still noticed
        write_json(path, {"revision": rev if rev is not None else recorded,
                          "fast_revision": fast_rev if fast_rev is not None else recorded_fast, "recorded": now()})
    except OSError:
        pass  # the notice is still given; it comes again at the next prompt
    return text


def main(argv):
    if not argv or argv[0] not in ("update", "status", "session-start", "prompt"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd in ("session-start", "prompt"):
        event = "SessionStart" if cmd == "session-start" else "UserPromptSubmit"
        try:
            text = session_start() if cmd == "session-start" else prompt()
        except Exception as exc:  # a hook never fails the session, and never fails silently
            print(json.dumps({"systemMessage": f"pipeline_sync.py {cmd} hit an internal error and did nothing: "
                                               f"{exc.__class__.__name__}: {exc}"[:300]}))
            return 0
        if text and cmd == "session-start":
            print(json.dumps({"systemMessage": text}))
        elif text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
        return 0
    unknown = [a for a in argv[1:] if a not in ("--json", "--no-pull") or (cmd == "status" and a == "--no-pull")]
    if unknown:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if cmd == "status":
        s = status()
        if "--json" in argv:
            print(json.dumps(s, indent=1))
        else:
            print_status(s)
        return 0
    code, result = update(no_pull="--no-pull" in argv)
    if "--json" in argv:
        print(json.dumps(result, indent=1))
    else:
        print_update(result)
    return code


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
