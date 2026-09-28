#!/usr/bin/env python3
"""PreToolUse hook: heavy local work goes through the machine-wide lock (heavy.py).

Register it for Bash and for the browser-automation tools:
  matcher "Bash"
  matcher "mcp__plugin_playwright_playwright__.*|mcp__plugin_chrome-devtools-mcp_chrome-devtools__.*|mcp__claude-in-chrome__.*"

Bash: a bounded heavy command (test suite, build, typecheck, simulator run, container build, gate.sh)
that does not start with the `heavy.py run` wrapper is denied with the exact command to run instead (the
heavy part alone, owned by this session); a server command (dev, start, serve, preview) is denied the same
way with `heavy.py serve`. A chained command is never suggested: the heavy part is named and runs as its own
call. The project adds bounded heavy commands under "Heavy commands" in docs/project/gate.md.
Browser automation: the browser MCP tools and the playwright-cli command take or refresh this session's
browser lease (playwright-cli close / close-all / kill-all release it); if another session holds a lease or
a bounded job, the call is denied with who holds it, so the agent waits instead of adding load.
Set HEAVY_GUARD_DISABLE=1 to switch the guard off explicitly. On an internal error the guard allows the
call and says so in a visible message (it never blocks work because of its own bug).
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HEAVY_PY = Path(__file__).resolve().parents[1] / "skills/_shared/scripts/heavy.py"
if not HEAVY_PY.exists():
    HEAVY_PY = Path.home() / ".claude/skills/_shared/scripts/heavy.py"

BOUNDED = [
    r"(npm|pnpm|yarn|bun)( run)? (test|build|e2e|typecheck|check)\b",
    r"(npm|pnpm|yarn|bun) (exec|dlx) (tsc|vitest|jest|playwright)\b",
    r"npx( --no-install)? (tsc|vitest|jest|playwright test|next build|vite build|webpack)\b",
    r"(tsc|vitest|jest)\b",
    r"playwright test\b",
    r"(python3?|uv run|poetry run)( -m)? (pytest|unittest)\b",
    r"pytest\b",
    r"cargo (build|test|run|clippy|check|bench)\b",
    r"go (build|test|vet)\b",
    r"(xcodebuild|swift (build|test)|xcrun simctl (boot|install|launch))\b",
    r"(\./gradlew|gradle|mvn) ",
    r"make( |$)",
    r"docker (build|compose up|run)\b",
    r"((ba|z)?sh\s+)?\S*gate\.sh\b",
]
SERVERS = [
    r"(npm|pnpm|yarn|bun)( run)? (dev|start|serve|preview)\b",
    r"npx( --no-install)? (next dev|next start|vite( |$)|serve\b)",
    r"(python3? -m http\.server|uvicorn|gunicorn|flask run|rails s(erver)?\b|php -S)",
]
PREFIX = re.compile(r"^((\w+=\S*\s+)+|time\s+|timeout\s+\d+\S*\s+|nice\s+(-n\s*\d+\s+)?)+")
WRAPPED = re.compile(r"^(python3?\s+)?\S*heavy\.py\s+(run|serve|lease|release|status|held)\b")
PLAYWRIGHT_CLI = re.compile(r"^(npx\s+(-y\s+)?@playwright/cli(@\S+)?|playwright-cli)\b(.*)$")


def compile_all(patterns):
    return [re.compile(r"^" + p) for p in patterns]


def project_extras(cwd):
    sys.path.insert(0, str(HEAVY_PY.parent))
    try:
        from gate_keys import read_keys  # noqa: E402
    except ImportError:
        return []
    p = Path(cwd).resolve()
    for c in [p, *p.parents]:
        if (c / "docs/project").is_dir() or (c / "AGENTS.md").is_file():
            return [re.compile(r"^" + re.escape(x)) for x in read_keys(c)["Heavy commands"]]
    return []


HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1([^\n]*)\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SHELL = r"(?:/\S*/)?(?:ba|z|da|k)?sh"
# `bash -c '...'`, `sh -lc "..."`, `bash -l -c '...'`: the quoted script is commands in its own right
SHELL_C = re.compile(rf"(?<![\w/.-]){SHELL}((?:\s+-[a-zA-Z]+)+)\s+(['\"])(.*?)(?<!\\)\2", re.S)
# a shell that reads its script from standard input: `bash`, `sh -s`, `bash -s -- arg`
SHELL_STDIN = re.compile(rf"(?:^|[;&|(]\s*|\s){SHELL}(?:\s+-[a-zA-Z]+)*(?:\s+--(?:\s+\S+)*)?\s*$")
PIPE_TO_SHELL = re.compile(rf"\|\s*{SHELL}(?:\s+-[a-zA-Z]+)*\s*(?:$|[;&|])")


def quote_map(text):
    """For each character, whether it sits inside a quoted string."""
    inside, quote, escaped = [], None, False
    for ch in text:
        if quote:
            inside.append(True)
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
        else:
            inside.append(False)
            if ch in "'\"":
                quote = ch
    return inside


def mask_quoted(text):
    """Blank the separators and newlines inside quoted strings, so text passed as data (a commit message, an
    echo) is never read as a command of its own."""
    return "".join(" " if q and ch in ";|&\n" else ch for ch, q in zip(text, quote_map(text)))


def strip_comments(text):
    """Drop `# ...` to the end of the line when the # starts a word outside quotes (a shell comment)."""
    inside, out, skip = quote_map(text), [], False
    for i, ch in enumerate(text):
        if skip:
            if ch == "\n":
                skip = False
                out.append(ch)
            continue
        if ch == "#" and not inside[i] and (i == 0 or text[i - 1] in " \t\n;&|("):
            skip = True
            continue
        out.append(ch)
    return "".join(out)


def segments(command):
    """The commands a shell line would run. Heredoc bodies and quoted text are data, unless a shell reads them
    (`bash <<EOF`, `sh -s <<EOF`, `cat <<EOF | bash`, `bash -c '...'`, `sh -lc "..."`), in which case they
    are split as commands in their own right. Comments are not commands."""
    scripts = []

    def head(m):
        line_start = command.rfind("\n", 0, m.start()) + 1
        before, rest = command[line_start:m.start()], m.group(3)
        if SHELL_STDIN.search(before) or PIPE_TO_SHELL.search(rest):
            scripts.append(m.group(4))
        return m.group(0).split("\n", 1)[0]

    text = strip_comments(HEREDOC.sub(head, command))
    inside = quote_map(text)
    scripts += [m.group(3) for m in SHELL_C.finditer(text) if "c" in m.group(1) and not inside[m.start()]]
    for part in re.split(r"&&|\|\||;|\||\n", mask_quoted(text)):
        part = PREFIX.sub("", part.strip().lstrip("(").strip())
        if part:
            yield part
    for script in scripts:
        yield from segments(script)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def suggestion(mode, seg, owner, whole):
    wrapped = f"python3 {HEAVY_PY} {mode} --owner {owner} -- {seg}"
    if seg.strip() != whole.strip():
        return (f"{wrapped}  (run it as its own call; run the other parts of your command separately, since a "
                "chained command cannot be approved automatically)")
    return wrapped


def owner_of(data):
    return (data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
            or "unknown")


def check_bash(data):
    command = (data.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    owner = owner_of(data)
    bounded = compile_all(BOUNDED) + project_extras(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    servers = compile_all(SERVERS)
    for seg in segments(command):
        if WRAPPED.search(seg):
            continue
        pw = PLAYWRIGHT_CLI.search(seg)
        if pw:
            words = pw.group(4).split()
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-s", "--session") else words[1:]
            if words and words[0] in ("close", "close-all", "kill-all"):
                subprocess.run([sys.executable, str(HEAVY_PY), "release", "--owner", owner, "--kind", "browser"],
                               capture_output=True, timeout=10)
                continue
            denied = take_browser_lease(owner)
            if denied:
                return denied
            continue
        if any(rx.search(seg) for rx in servers):
            return deny(f"'{seg[:60]}' starts a server, which is long-lived heavy work. Run it through the "
                        f"lease so other sessions know: {suggestion('serve', seg, owner, command)}  (run it in the "
                        "background; the lease ends when the server exits).")
        if any(rx.search(seg) for rx in bounded):
            return deny(f"'{seg[:60]}' is a heavy local job. Only one runs at a time on this machine, so it "
                        f"goes through the lock. Run instead: {suggestion('run', seg, owner, command)}  (it waits if "
                        "another heavy job is running and reports BUSY if the wait runs out).")
    return 0


def take_browser_lease(owner):
    r = subprocess.run([sys.executable, str(HEAVY_PY), "lease", "browser", "--owner", owner, "--ttl", "120"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode == 75:
        return deny("Browser automation is heavy local work and another session holds the machine: "
                    f"{r.stderr.strip()}. Wait for it to finish, then retry this call.")
    return None


BROWSER_CLOSE = re.compile(r"(browser_close|close_page|tabs_close_mcp)$")


def check_browser(data):
    """Every browser call takes or refreshes this session's two-minute lease; closing the browser releases it."""
    owner = owner_of(data)
    if BROWSER_CLOSE.search(str(data.get("tool_name", ""))):
        subprocess.run([sys.executable, str(HEAVY_PY), "release", "--owner", owner, "--kind", "browser"],
                       capture_output=True, timeout=10)
        return 0
    return take_browser_lease(owner) or 0


def main():
    if os.environ.get("HEAVY_GUARD_DISABLE") == "1":
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        tool = data.get("tool_name") or ""
        if tool == "Bash":
            return check_bash(data)
        if tool.startswith(("mcp__plugin_playwright", "mcp__plugin_chrome-devtools-mcp", "mcp__claude-in-chrome")):
            return check_browser(data)
        return 0
    except Exception as exc:  # the guard must never block work because of its own bug, nor fail silently
        print(json.dumps({"systemMessage": f"heavy-guard hit an internal error and allowed the call: "
                                           f"{exc.__class__.__name__}: {exc}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
