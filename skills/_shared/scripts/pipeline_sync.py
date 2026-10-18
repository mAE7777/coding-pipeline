#!/usr/bin/env python3
"""Update the installed pipeline from its repository in one command, and tell every open session when the skill
text it already read is out of date. Nothing here pulls or installs in the background.

Usage:
  pipeline_sync.py update [--no-pull] [--json]   pull the repository, install it, register its hooks
  pipeline_sync.py status [--json]               what is installed, what the repository holds, runs in progress
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

status. The installed revision and time, the repository's HEAD and branch, how far it is ahead of or behind its
upstream as of the last fetch (no network), uncommitted changes, the last update, and runs in progress.

Runs in progress. gate_run.py and run_isolated.py write ~/.claude/.pipeline-runs/<pid>.json ({pid, script,
project, started}) when they start and remove it when they end (a run stopped by a signal too). update counts an
entry whose process is alive and still runs that script as busy, and removes the others.

session-start (SessionStart). Records the revision installed now for this session in
~/.claude/.pipeline-sessions/<session_id>.json (a resumed or forked session keeps the revision it already has on
record, since its conversation holds the text it read then), and when the repository's local HEAD (no network)
is not the installed revision, prints a message for the owner: "The pipeline repository has <n> commit(s) not
installed (<before>..<after>). Type /pipeline update." Records older than 14 days are removed.

prompt (UserPromptSubmit). Two small file reads, no git, no network. When the manifest's revision differs from
the one recorded for this session, it adds a notice to the session's context once: the skill text read earlier
in the session is out of date, re-read the SKILL.md of the skill in use (or invoke it again) and the references
the next step relies on; with the skills and shared references that changed when the update history reaches
back to the session's revision. Then the new revision is recorded for the session. A session with no record
(started before this hook existed) records the current revision silently.

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
        write_json(sync_path(), {"time": now(), "before": result.get("before"), "after": result.get("after"),
                                 "result": result["result"], "reason": result.get("reason"),
                                 "changed": result.get("changed"), "history": history[-HISTORY:]})
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
              "notes": [], "log": [], "log_more": 0, "changed": None, "repo": None}
    me = register_run("pipeline_sync.py update")  # one update at a time: a second one finds this entry
    try:
        code = _update(no_pull, result)
    finally:
        unregister_run(me)
    write_sync(result)
    return code, result


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


def print_update(code, result):
    r = result
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
        if r.get("before") or r.get("after"):
            print(f"revision: {short(r['before'])} installed before; repository at {short(r['after'])}")
        if r.get("output"):
            print(r["output"])
    for note in r.get("notes") or []:
        print(f"note: {note}")


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
        print(f"last update: {lu.get('result')} at {lu.get('time')} ({short(lu.get('before'))} -> "
              f"{short(lu.get('after'))})" + (f": {lu['reason']}" if lu.get("reason") else ""))
    print(f"runs in progress: {describe_runs(s['runs']) if s['runs'] else 'none'}")
    for p in s["problems"]:
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
    if manifest is None:
        return None
    rev = manifest.get("revision")
    path = session_file(data)
    if path is not None and isinstance(rev, str):
        rec = read_json(path)
        # A resumed or forked conversation still holds the text it read before: its record stays.
        keep = data.get("source") in ("resume", "fork") and rec and isinstance(rec.get("revision"), str)
        if not keep:
            try:
                write_json(path, {"revision": rev, "recorded": now()})
            except OSError:
                pass  # the prompt hook records it later
    cutoff = time.time() - SESSION_DAYS * 86400
    for old in sessions_dir().glob("*.json") if sessions_dir().is_dir() else []:
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    repo = manifest.get("repo")
    if not isinstance(repo, str) or not repo or not Path(repo).is_dir():
        return None
    code, head, _ = git(repo, "rev-parse", "HEAD", timeout=5)
    if code != 0 or not head or plain(rev) == head:
        return None
    code, count, _ = git(repo, "rev-list", "--count", f"{plain(rev)}..{head}", timeout=5)
    if code == 0 and count.isdigit() and int(count) > 0:
        return (f"The pipeline repository has {count} commit(s) not installed ({short(plain(rev))}..{short(head)}). "
                "Type /pipeline update.")
    return (f"The pipeline repository's HEAD ({short(head)}) is not the revision installed in ~/.claude "
            f"({short(rev)}). Type /pipeline update to install it.")


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


def notice(before, after):
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
    return text + " If this session has used no pipeline skill, nothing needs doing."


def prompt():
    data = read_hook_input()
    path = session_file(data)
    if path is None:
        return None
    rev = installed_revision()
    if rev is None:
        return None
    rec = read_json(path)
    recorded = rec.get("revision") if rec else None
    if recorded == rev:
        try:
            if path.stat().st_mtime < time.time() - 86400:
                os.utime(path)  # a session still open is never pruned as old
        except OSError:
            pass
        return None
    text = notice(recorded, rev) if isinstance(recorded, str) else None  # no record: started before this hook
    try:
        write_json(path, {"revision": rev, "recorded": now()})
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
        print_update(code, result)
    return code


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
