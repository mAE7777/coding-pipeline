#!/usr/bin/env python3
"""Machine-wide control of heavy local work, so one heavy job runs at a time across Claude Code
sessions, subagents, isolated runs, and Codex.

Usage:
  heavy.py run   [--wait <s>] [--timeout <s>] [--owner <id>] -- <command...>   a bounded job (build, tests,
                                                              typecheck, gate)
  heavy.py serve [--wait <s>] [--owner <id>] -- <command...>   a long-lived server, holds a lease while it runs
  heavy.py lease browser [--owner <id>] [--ttl <s>]             take or refresh a browser-automation lease
  heavy.py release [--owner <id>] [--kind browser|serve]       drop this owner's leases (all, or one kind)
  heavy.py status                                              who holds what
  heavy.py held [--owner <id>]                                 exit 0 if anything foreign is held, else 1

Two mechanisms:
  - Bounded jobs take an exclusive kernel file lock (fcntl.flock) on $HEAVY_LOCK_DIR/heavy.lock (default
    /tmp/heavy-lock-<uid>: a path Claude Code sessions, the isolated checkers, and Codex's default
    workspace-write sandbox, which keeps /tmp writable, can all open). The kernel releases it when the holder
    exits or crashes, so it never goes stale. A lock folder that cannot be opened ends the call with exit 77
    and the reason, never a traceback and never a run without the lock. The command runs in its own process group, which is terminated when the job ends, so stray
    workers do not outlive it.
  - Long-lived work (a dev server, a browser session) holds a lease file owned by one session. A serve
    lease lives while its process lives; a browser lease lives until its time-to-live (default 120s) runs out
    unless refreshed, and every browser call refreshes it, so an idle browser frees the machine within two
    minutes. The owner's own bounded jobs may run alongside its leases; other owners wait.

The owner is --owner, else $HEAVY_OWNER, else this command's session (session_env.py: $CLAUDE_CODE_SESSION_ID in
Claude Code, $CODEX_THREAD_ID in Codex). A bounded
run without any of these uses "pid-<parent pid>"; serve, lease, and release refuse to run without a real
owner, because a per-call pid would make a session block itself.
A bounded job's command runs with HEAVY_LOCK_HELD set, so a heavy.py run nested inside it (gate.sh calling
a project script, browse.py wrapping itself) re-enters instead of waiting on its own lock.
Waiting prints who holds what. When --wait runs out (default 540s, under the shell tool's 10-minute
ceiling) the command is not run and the exit code is 75 with the holder's details: an explicit BUSY,
never a silent skip. --timeout ends the job's whole process group after that many seconds and returns
124. Otherwise the command's own exit code is returned.
"""
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BUSY = 75
NOLOCK = 77


class LockUnavailable(Exception):
    pass


def default_lock_dir():
    return Path(f"/tmp/heavy-lock-{os.getuid()}")


def lock_dir():
    d = Path(os.environ.get("HEAVY_LOCK_DIR") or default_lock_dir())
    try:
        (d / "leases").mkdir(parents=True, exist_ok=True)
        if not os.access(d, os.W_OK):
            raise PermissionError(f"{d} is not writable")
    except OSError as exc:
        raise LockUnavailable(f"cannot open the heavy lock at {d}: {exc}") from exc
    return d


def env_owner():
    if os.environ.get("HEAVY_OWNER"):
        return os.environ["HEAVY_OWNER"]
    from session_env import current  # noqa: E402
    tool, sid = current()
    return sid if tool in ("claude", "codex") else ""


def default_owner():
    return env_owner() or f"pid-{os.getppid()}"


def pid_alive(pid):
    """A process we may not signal (EPERM, for example from inside a sandbox) is still alive."""
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False


def live_leases():
    out = []
    for f in (lock_dir() / "leases").glob("*.json"):
        try:
            lease = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        alive = pid_alive(lease.get("pid")) if lease.get("kind") == "serve" else lease.get("expires", 0) > time.time()
        if alive:
            out.append(lease)
        else:
            f.unlink(missing_ok=True)
    return out


def foreign_leases(owner):
    return [l for l in live_leases() if l.get("owner") != owner]


def describe_lease(l):
    return f"{l.get('kind')} lease of {l.get('owner')} ('{l.get('command', '')[:60]}', since {l.get('since')})"


def holder_info():
    try:
        return json.loads((lock_dir() / "holder.json").read_text())
    except (OSError, ValueError):
        return {}


def describe_holder(info):
    if not info:
        return "an unknown process"
    return f"{info.get('owner')} (pid {info.get('pid')}, '{info.get('command', '?')[:60]}', since {info.get('since')})"


def try_flock(fh):
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def flock_held():
    with open(lock_dir() / "heavy.lock", "a+") as fh:
        if try_flock(fh):
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False
        return True


def parse(argv):
    """Options may appear anywhere before "--"; everything after "--" is the command."""
    opts = {"wait": 540, "owner": default_owner(), "ttl": 120, "timeout": 0,
            "owner_given": bool(env_owner())}
    positional, command = [], []
    tokens = list(argv)
    while tokens:
        tok = tokens.pop(0)
        if tok == "--":
            command = tokens
            break
        if tok in ("--wait", "--owner", "--ttl", "--timeout", "--kind"):
            if not tokens:
                raise SystemExit(2)
            val = tokens.pop(0)
            opts[tok[2:]] = int(val) if tok in ("--wait", "--ttl", "--timeout") else val
            if tok == "--owner":
                opts["owner_given"] = True
        else:
            positional.append(tok)
    return opts, (command if command else positional)


def say(msg):
    print(f"heavy.py: {msg}", file=sys.stderr)


def wait_for(opts, need_flock, fh=None):
    """Wait until no foreign lease is live and (if need_flock) the flock is ours. True on success."""
    deadline = time.time() + opts["wait"]
    announced = False
    while True:
        foreign = foreign_leases(opts["owner"])
        got = True
        if not foreign and need_flock:
            got = try_flock(fh)
        elif not foreign and not need_flock:
            got = not flock_held() or holder_info().get("owner") == opts["owner"]
        if not foreign and got:
            return True
        if not announced:
            blocker = describe_lease(foreign[0]) if foreign else f"a bounded job of {describe_holder(holder_info())}"
            say(f"waiting: {blocker}")
            announced = True
        if time.time() >= deadline:
            blocker = "; ".join(describe_lease(l) for l in foreign) if foreign else describe_holder(holder_info())
            say(f"BUSY after {opts['wait']}s, held by {blocker}. Nothing was run. Retry when it finishes.")
            return False
        time.sleep(2)


def run_group(argv, env=None, timeout=0):
    """Run a command in its own process group; terminate the group when it ends, on a signal, or when
    the timeout (seconds, 0 = none) runs out (exit 124)."""
    try:
        proc = subprocess.Popen(argv, start_new_session=True, env=env)
    except FileNotFoundError:
        say(f"command not found: {argv[0]}")
        return 127, None

    def forward(signum, _frame):
        try:
            os.killpg(proc.pid, signum)
        except OSError:
            pass
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, forward)
    try:
        code = proc.wait(timeout=timeout or None)
    except subprocess.TimeoutExpired:
        say(f"TIMEOUT after {timeout}s: the job's process group was stopped")
        forward(signal.SIGTERM, None)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forward(signal.SIGKILL, None)
            proc.wait()
        code = 124
    for sig, pause in ((signal.SIGTERM, 1.5), (signal.SIGKILL, 0)):
        try:
            os.killpg(proc.pid, sig)
            time.sleep(pause)
        except OSError:
            break
    return code, proc.pid


def reentry_ok():
    """True when this call runs inside a bounded job that holds the lock (HEAVY_LOCK_HELD=<owner>:<pid>
    names the live heavy.py process that took it)."""
    token = os.environ.get("HEAVY_LOCK_HELD", "")
    if ":" not in token:
        return False
    pid = token.rsplit(":", 1)[1]
    return pid_alive(pid) and str(holder_info().get("pid")) == pid and flock_held()


def cmd_run(argv):
    opts, command = parse(argv)
    if not command:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if reentry_ok():
        log_event("run-nested", opts["owner"], command)
        code, _ = run_group(command, timeout=opts["timeout"])
        return code
    fh = open(lock_dir() / "heavy.lock", "a+")
    if not wait_for(opts, need_flock=True, fh=fh):
        return BUSY
    (lock_dir() / "holder.json").write_text(json.dumps({
        "owner": opts["owner"], "pid": os.getpid(), "command": " ".join(command), "cwd": os.getcwd(),
        "since": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    log_event("run-start", opts["owner"], command)
    env = {**os.environ, "HEAVY_LOCK_HELD": f"{opts['owner']}:{os.getpid()}"}
    try:
        code, _ = run_group(command, env=env, timeout=opts["timeout"])
        return code
    finally:
        log_event("run-end", opts["owner"], command)
        (lock_dir() / "holder.json").unlink(missing_ok=True)
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def write_lease(owner, kind, pid, command, ttl=None):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in owner)
    path = lock_dir() / "leases" / f"{safe}-{kind}.json"
    lease = {"owner": owner, "kind": kind, "pid": pid, "command": command,
             "since": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if ttl:
        lease["expires"] = time.time() + ttl
    path.write_text(json.dumps(lease))
    return path


def need_owner(opts, what):
    if opts["owner_given"]:
        return True
    say(f"{what} needs an owner: pass --owner <session id> (or run inside a Claude Code or Codex session)")
    return False


def cmd_serve(argv):
    opts, command = parse(argv)
    if not command:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if not need_owner(opts, "serve"):
        return 2
    if not wait_for(opts, need_flock=False):
        return BUSY
    try:
        proc = subprocess.Popen(command, start_new_session=True)
    except FileNotFoundError:
        say(f"command not found: {command[0]}")
        return 127
    path = write_lease(opts["owner"], "serve", proc.pid, " ".join(command))
    log_event("serve-start", opts["owner"], command)

    def stop(signum, _frame):
        try:
            os.killpg(proc.pid, signum)
        except OSError:
            pass
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        return proc.wait()
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        log_event("serve-end", opts["owner"], command)


def cmd_lease(argv):
    opts, positional = parse(argv)
    if positional != ["browser"]:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if not need_owner(opts, "lease"):
        return 2
    foreign = foreign_leases(opts["owner"])
    busy_flock = flock_held() and holder_info().get("owner") != opts["owner"]
    if foreign or busy_flock:
        blocker = describe_lease(foreign[0]) if foreign else f"a bounded job of {describe_holder(holder_info())}"
        say(f"BUSY: {blocker}")
        return BUSY
    write_lease(opts["owner"], "browser", os.getpid(), "browser automation", ttl=opts["ttl"])
    return 0


def cmd_release(argv):
    opts, _ = parse(argv)
    if not need_owner(opts, "release"):
        return 2
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in opts["owner"])
    kind = opts.get("kind") or "*"
    for f in (lock_dir() / "leases").glob(f"{safe}-{kind}.json"):
        f.unlink(missing_ok=True)
    return 0


def log_event(kind, owner, command):
    try:
        with open(lock_dir() / "events.log", "a") as f:
            f.write(json.dumps({"t": time.time(), "event": kind, "owner": owner,
                                "command": " ".join(command)[:200]}) + "\n")
    except OSError:
        pass


def main(argv):
    try:
        return dispatch(argv)
    except LockUnavailable as exc:
        print(f"heavy.py: BLOCKED: {exc}. Nothing was run (exit {NOLOCK}).", file=sys.stderr)
        return NOLOCK


def dispatch(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "run":
        return cmd_run(rest)
    if cmd == "serve":
        return cmd_serve(rest)
    if cmd == "lease":
        return cmd_lease(rest)
    if cmd == "release":
        return cmd_release(rest)
    if cmd == "status":
        leases = live_leases()
        print(f"bounded: {'held by ' + describe_holder(holder_info()) if flock_held() else 'free'}")
        for l in leases:
            print(f"lease: {describe_lease(l)}")
        return 0
    if cmd == "held":
        opts, _ = parse(rest)
        busy = (flock_held() and holder_info().get("owner") != opts["owner"]) or bool(foreign_leases(opts["owner"]))
        return 0 if busy else 1
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
