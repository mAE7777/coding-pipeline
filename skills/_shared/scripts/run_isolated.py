#!/usr/bin/env python3
"""Run one checker as an isolated headless process inside a prepared directory.

Usage:
  run_isolated.py <role> --dir <workdir> --out <evidence-dir> (--pack <file> | --render <render_pack args...> --)
                  [--project <real project>] [--mode demo] [--resume <session-id>] [--family claude|codex|auto]
                  [--agent-file <path>] [--canary <text> ...] [--deny <path> ...] [--allow-read <path> ...]
                  [--network <host> ...] [--effort xhigh] [--timeout <seconds>] [--dry-run]

Roles: code-verifier, loyal-evaluator, gate-judge, cold-reader, claim-verifier.
--dir auto gives a checker that reads only its pack (cold-reader, claim-verifier) a fresh empty private
folder, removed when the run ends.
A real gate run takes longer than a shell tool call may last: start this in the background and wait for
<evidence-dir>/<role>.summary.json.

Inputs. The pack is a file (--pack, used by the fixture harness) or rendered by render_pack.py into the
evidence folder immediately before launch (--render ... --), so nothing editable sits between rendering and
running; its sha256 is recorded. For the loyal-evaluator's first pass the pack is checked against
intent.md first, and a hit stops the run with status LEAK. The agent definition comes from --agent-file
(staging) or ~/.claude/agents/<role>.md and is passed inline, so the checker runs exactly that text.

Claude family: `claude -p --agents <file> --agent <role>` with cwd=<workdir>, the pack on standard input, and
  --restricted                 no user, project, or local settings files (no user CLAUDE.md rules, hooks,
                               permissions, or plugins); file tools confined to the working directories
  --tools <role's tools>       the only tools that exist in the session
  --disable-slash-commands     no skills
  --strict-mcp-config          no MCP servers
  --permission-mode dontAsk    anything not allowed is refused
  --session-id <uuid>          known before launch: the child's heavy-lock owner, released when it exits
  --settings <generated>       the OS sandbox, on with no unsandboxed fallback and failing if unavailable:
                               reads denied for the whole home folder (the real project included), /Volumes,
                               the user temp folder, and every other session's temp folder, then re-opened
                               only for the workdir, the
                               shared scripts, the stack packs, the common toolchain folders, and
                               --allow-read / "Gate read allow" paths; writes only in the workdir, the tool
                               caches, and the heavy-lock folder; network only to localhost (plus --network
                               hosts) with local port binding allowed; browse.py exempt from the sandbox when
                               called as `python3 <browse.py> --root <workdir> ...` (it enforces its own
                               boundary); the heavy-lock guard as a PreToolUse hook
  CLAUDE_CODE_TMPDIR           a private temp folder under ~/.gate-copies, removed after the run
  --output-format stream-json --verbose --effort <e>
Before launch, a server listening on a TCP port from inside the real project is BLOCKED (a checker could
read the project through it); stop it first.

Codex family (code-verifier only): `codex exec` inside the same kind of read fence, built as a macOS
sandbox-exec profile (Codex's own sandbox cannot nest inside it, so it runs with -s danger-full-access and
the profile is the boundary), with CODEX_HOME pointing at a fresh folder that links only auth.json, and
HEAVY_OWNER set to the child. A quota, sign-in, or version refusal is status UNAVAILABLE. --family auto tries
Codex and runs Claude when Codex is UNAVAILABLE, recording the switch and its reason in the summary.

Writes <role>[-demo][-pass2].{pack.md,agents.json,jsonl,result.md,summary.json,settings.json|sb} to
<evidence-dir>. Status: OK, INCONCLUSIVE (a role that must execute ran no tool), LEAK (a --canary string
appeared, or the pass-1 pack carried intent), BLOCKED (a server from the real project is running),
UNAVAILABLE (Codex could not serve the run), or ERROR (non-zero exit, timeout, or no result). A project that
names "Gate network" hosts is reviewed on Claude even under --family codex or auto (the switch is recorded):
the Codex fence opens ports, not hosts. Exit 0 for
OK, 1 otherwise, 2 on bad usage. Never uses --dangerously-skip-permissions.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
ROLES = {
    "code-verifier": ["Read", "Grep", "Glob", "Bash", "Edit", "Write"],
    "loyal-evaluator": ["Read", "Grep", "Glob", "Bash"],
    "gate-judge": ["Read", "Grep", "Glob"],
    "cold-reader": ["Read", "Grep", "Glob"],
    "claim-verifier": ["Read", "WebSearch", "WebFetch"],
}
MIN_TOOLS = {"code-verifier": 1, "loyal-evaluator": 1, "claim-verifier": 1, "gate-judge": 0, "cold-reader": 0}
SHARED = HOME / ".claude/skills/_shared"
LOCK_DIR = Path(os.environ.get("HEAVY_LOCK_DIR") or f"/tmp/heavy-lock-{os.getuid()}").resolve()
TOOLCHAINS = [".volta", ".nvm", ".npm", ".bun", ".deno", ".cargo", ".rustup", "go", ".pyenv", ".local/bin",
              ".local/lib", ".local/share/uv", ".local/share/pnpm", "Library/pnpm", "Library/Python",
              ".gradle", ".m2", ".gem", ".rbenv", ".swiftpm", "Library/Developer",
              ".gitconfig", ".config/git", ".yarn", ".pub-cache", ".dotnet", ".nuget", ".android",
              "Library/Android", ".expo", ".codex/packages"]
# Dependency caches a build or a test run reads and writes, by name: Library/Caches and ~/.cache as a whole
# also hold every app's and browser's cache (Safari, Chrome, a browser tool's saved profile with its logins).
CACHES = ["Library/Caches/" + c for c in ("pip", "pypoetry", "node-gyp", "Yarn", "pnpm", "go-build", "golangci-lint",
                                          "typescript", "deno", "esbuild", "Cypress", "org.swift.swiftpm", "CocoaPods",
                                          "electron", "turbo", "bun", "Codex")] + \
         [".cache/" + c for c in ("uv", "pip", "node-gyp", "prisma", "pre-commit", "turbo", "yarn", "typescript",
                                  "go-build", "deno", "codex-runtimes")]
WRITE_CACHES = [".npm", "Library/Developer/Xcode/DerivedData", ".cargo/registry", ".gradle", ".m2",
                ".bun/install/cache", ".local/share/pnpm", "Library/pnpm"] + CACHES
BROWSER_BUILD = re.compile(r"^(chromium|chromium_headless_shell|chromium-headless-shell|chrome|firefox|webkit|ffmpeg)"
                           r"[-_]\d+$")
DENY_INSIDE_ALLOWED = [".cache/pipeline-fixtures", ".cache/gate-copies"]
LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
UNAVAILABLE_MARKERS = ("usage limit", "requires a newer version", "not logged in", "please log in",
                       "authentication", "rate limit", "quota")


def browser_builds():
    """Installed browser builds, opened read-only; never a saved browser profile (mcp-chrome-*, a CLI's daemon
    sessions), which holds the owner's logins and history."""
    out = []
    for base in (HOME / "Library/Caches/ms-playwright", HOME / ".cache/ms-playwright"):
        if base.is_dir():
            out += [p for p in base.iterdir() if BROWSER_BUILD.match(p.name) or p.name == ".links"]
    return out + [HOME / d for d in (".cache/puppeteer", ".cache/selenium") if (HOME / d).is_dir()]


def cache_reads():
    return [HOME / t for t in TOOLCHAINS + CACHES if (HOME / t).exists()] + browser_builds()


def perm(p):
    s = str(p)
    return "/" + s if s.startswith("/") else s


def first_existing(*candidates):
    for c in candidates:
        if c.exists():
            return c
    return None


def guard_hook():
    return first_existing(HOME / ".claude/hooks/heavy-guard.py", HERE.parents[2] / "hooks/heavy-guard.py")


def browse_script():
    return first_existing(SHARED / "scripts/browse.py", HERE / "browse.py")


def stacks_dir():
    return first_existing(SHARED / "references/stacks", HERE.parent / "references/stacks")


def protocols_dir():
    return first_existing(HOME / ".claude/skills/gate/references", HERE.parents[1] / "gate/references")


def private_tmp_dir():
    d = HOME / ".gate-copies" / f"tmp-{secrets.token_hex(6)}"
    d.mkdir(parents=True, mode=0o700)
    return d


def uid_temp_entries(exclude):
    base = Path(f"/private/tmp/claude-{os.getuid()}")
    if not base.is_dir():
        return []
    return [str(p) for p in base.iterdir() if str(p) != str(exclude)]


def settings(role, workdir, deny=(), project=None, allow_read=(), network=(), private_tmp=None):
    workdir = Path(workdir)
    explicit = [str(Path(d).resolve()) for d in deny]
    if project:
        explicit.append(str(Path(project).resolve()))
    # the whole home folder is already denied; an explicit deny never covers the checker's own folder
    wd = str(workdir.resolve())
    explicit = [d for d in explicit if not (wd == d or wd.startswith(d + "/"))]
    user_tmp = os.environ.get("TMPDIR", "").rstrip("/")
    deny_read = [str(HOME), "/Volumes", "/Users/Shared"] + explicit
    deny_read += [str(HOME / d) for d in DENY_INSIDE_ALLOWED]
    if user_tmp.startswith("/var/folders") or user_tmp.startswith("/private/var/folders"):
        deny_read.append(user_tmp)
    deny_read += uid_temp_entries(private_tmp)
    scripts = [str(HERE)] + ([str(SHARED / "scripts")] if (SHARED / "scripts").exists() else [])
    stacks = stacks_dir()
    protocols = protocols_dir()
    allow = [str(workdir)] + scripts + ([str(stacks)] if stacks else []) + ([str(protocols)] if protocols else [])
    allow += [str(t) for t in cache_reads()]
    allow += [str(Path(p).expanduser()) for p in allow_read]
    if private_tmp:
        allow.append(str(private_tmp))
    write = [str(workdir), str(LOCK_DIR)] + [str(HOME / w) for w in WRITE_CACHES if (HOME / w).exists()]
    if private_tmp:
        write.append(str(private_tmp))
    cfg = {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "failIfUnavailable": True,
            "filesystem": {"denyRead": sorted(set(deny_read)), "allowRead": sorted(set(allow)),
                           "allowWrite": sorted(set(write))},
            # configd answers "what are the proxy settings"; without it uv (and other Rust HTTP clients) panic
            "network": {"allowedDomains": LOCAL_HOSTS + list(network), "strictAllowlist": True,
                        "allowLocalBinding": True, "allowMachLookup": ["com.apple.SystemConfiguration.configd"]},
        },
        "permissions": {"allow": [], "deny": []},
    }
    tools = ROLES[role]
    # --restricted already confines the file tools to the working directories, so they are allowed outright
    # (without an allow rule, dontAsk refuses even a search of the checker's own folder)
    cfg["permissions"]["allow"] += [t for t in ("Read", "Grep", "Glob") if t in tools]
    if "Bash" in tools:
        cfg["permissions"]["allow"].append("Bash")
        browse = browse_script()
        if browse:
            cfg["sandbox"]["excludedCommands"] = [f"python3 {browse} --root {workdir} *"]
        guard = guard_hook()
        if guard:
            cfg["hooks"] = {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": f"python3 {guard}", "timeout": 15}]}]}
    for t in ("Edit", "Write"):
        if t in tools:
            cfg["permissions"]["allow"].append(f"{t}({perm(workdir)}/**)")
    for t in ("WebFetch", "WebSearch"):
        if t in tools:
            cfg["permissions"]["allow"].append(t)
    if stacks:
        cfg["permissions"]["deny"] += [f"Edit({perm(stacks)}/**)", f"Write({perm(stacks)}/**)"]
    for d in explicit:
        cfg["permissions"]["deny"] += [f"{t}({perm(d)}/**)" for t in ("Read", "Grep", "Glob", "Edit", "Write")]
    return cfg


def read_agent(role, agent_file):
    path = Path(agent_file) if agent_file else HOME / ".claude/agents" / f"{role}.md"
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, flags=re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
    return path, meta, body.strip()


def agents_json(role, agent_file, out_path):
    path, meta, body = read_agent(role, agent_file)
    spec = {role: {"description": meta.get("description") or role, "prompt": body}}
    out_path.write_text(json.dumps(spec, indent=2))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def parse_claude_stream(lines):
    info = {"session_id": None, "model": None, "tool_uses": 0, "denials": [], "turns": None,
            "result": None, "is_error": None, "tools_seen": None}
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            info["session_id"] = ev.get("session_id")
            info["model"] = ev.get("model")
            info["tools_seen"] = ev.get("tools")
        elif t == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    info["tool_uses"] += 1
        elif t == "result":
            info["result"] = ev.get("result")
            info["turns"] = ev.get("num_turns")
            info["is_error"] = ev.get("is_error")
            info["denials"] = [str(d.get("tool_name")) + ":" + json.dumps(d.get("tool_input"))[:160]
                               for d in ev.get("permission_denials") or []]
            info["session_id"] = info["session_id"] or ev.get("session_id")
    return info


def parse_codex_stream(lines):
    info = {"session_id": None, "model": None, "tool_uses": 0, "denials": [], "turns": 0,
            "result": None, "is_error": False, "errors": []}
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type", "")
        if t == "thread.started":
            info["session_id"] = ev.get("thread_id")
        elif t == "turn.completed":
            info["turns"] += 1
        elif t in ("turn.failed", "error"):
            info["is_error"] = True
            msg = ev.get("message") or (ev.get("error") or {}).get("message") or ""
            info["errors"].append(str(msg)[:300])
        item = ev.get("item") or {}
        if t == "item.completed" and item.get("type") in ("command_execution", "file_change", "mcp_tool_call",
                                                           "web_search"):
            info["tool_uses"] += 1
        if t == "item.completed" and item.get("type") == "agent_message":
            info["result"] = item.get("text")
    return info


def codex_unavailable(info, stderr=""):
    """The marker that says Codex cannot serve (usage limit, login, version), from its JSON error events (where
    the usage limit arrives, observed 2026-09-27) or, failing that, its stderr."""
    blob = (" ".join(info.get("errors") or []) + " " + (stderr or "")).lower()
    return next((m for m in UNAVAILABLE_MARKERS if m in blob), None)


def pack_leaks(pack_text, project):
    """Distinctive intent phrases present in a pass-1 evaluator pack (which must carry none)."""
    sys.path.insert(0, str(HERE))
    from gate_copies import shingles  # noqa: E402
    intent = Path(project) / "docs/project/intent.md" if project else None
    if not intent or not intent.is_file():
        return []
    text = intent.read_text(encoding="utf-8")
    # The blind-safe persona is the one part of the intent pass 1 may carry: remove it, then compare the rest.
    rest = re.sub(r"^Persona \(blind\):.*$", "", text, flags=re.M)
    return sorted(shingles(pack_text) & shingles(rest))


def project_servers(project):
    """Listening TCP servers started from the real project: their working directory is inside it, or an argument
    names a path inside it (python -m http.server --directory <project>, npx serve <project>)."""
    if not project or not shutil.which("lsof"):
        return []
    real = str(Path(project).resolve())
    spellings = {real, str(Path(project).absolute()), str(Path(project))}
    out = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpc"], capture_output=True, text=True).stdout
    pids = {}
    current = None
    for line in out.splitlines():
        if line.startswith("p"):
            current = line[1:]
            pids[current] = ""
        elif line.startswith("c") and current:
            pids[current] = line[1:]
    hits = []
    for pid, name in pids.items():
        cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        for line in cwd.splitlines():
            if line.startswith("n") and (line[1:] == real or line[1:].startswith(real + "/")):
                hits.append(f"pid {pid} ({name}) in {line[1:]}")
        args = subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True, text=True).stdout
        named = any(re.search(rf"(^|[\s=]){re.escape(sp)}(/|\s|$)", args) for sp in spellings)
        if named and not any(h.startswith(f"pid {pid} ") for h in hits):
            hits.append(f"pid {pid} ({name}) serving {real}: {args.strip()[:120]}")
    return hits


def sb_quote(p):
    return json.dumps(str(p))


def codex_profile(workdir, codex_home, allow_read, private_tmp, codex_bin=None):
    reads = [workdir, codex_home, HOME / ".codex/auth.json", private_tmp, HERE] + \
        [d for d in (stacks_dir(), protocols_dir()) if d] + \
        ([Path(browse_script()).parent] if browse_script() else []) + \
        ([Path(codex_bin).parent] if codex_bin else []) + \
        cache_reads() + [Path(p).expanduser() for p in allow_read]
    writes = [workdir, codex_home, HOME / ".codex/auth.json", LOCK_DIR, private_tmp] + \
        [HOME / w for w in WRITE_CACHES if (HOME / w).exists()] + \
        [HOME / ".volta" / d for d in ("tmp", "log", "cache") if (HOME / ".volta" / d).exists()]
    user_tmp = os.environ.get("TMPDIR", "").rstrip("/")
    denied = [HOME, Path("/Volumes"), Path("/Users/Shared"), Path(f"/private/tmp/claude-{os.getuid()}")]
    if "/var/folders" in user_tmp:
        denied.append(Path(user_tmp).resolve())
    lines = ["(version 1)", "(allow default)",
             "(deny file-read* " + " ".join(f"(subpath {sb_quote(p)})" for p in denied) + ")"]
    lines += [f"(allow file-read* (subpath {sb_quote(p)}))" for p in reads if not str(p).endswith(".json")]
    lines += [f"(allow file-read* (literal {sb_quote(p)}))" for p in reads if str(p).endswith(".json")]
    lines += [f"(deny file-read* (subpath {sb_quote(HOME / d)}))" for d in DENY_INSIDE_ALLOWED]
    # Resolving an allowed path (Codex canonicalizes its home folder at startup) looks at every folder above it.
    # Those folders may be seen (their own attributes), never listed or read.
    above = sorted({str(a) for p in reads + writes for a in Path(p).parents})
    lines += [f"(allow file-read-metadata (literal {sb_quote(a)}))" for a in above]
    # Writes: nowhere but the copy, the private Codex home and temp folder, the heavy lock, and dependency caches.
    lines.append("(deny file-write*)")
    lines += [f"(allow file-write* (subpath {sb_quote(p)}))" for p in writes if not str(p).endswith(".json")]
    lines += [f"(allow file-write* (literal {sb_quote(p)}))" for p in writes if str(p).endswith(".json")]
    lines.append('(allow file-write* (subpath "/dev"))')
    # Outbound network: localhost, name lookups, and HTTPS only (the model's own API call runs inside this same
    # fence, so 443 must stay open). Probed 2026-09-27 with a stand-in process: ports 80 and 22 are refused,
    # 443, DNS, and a localhost server work. A server the checker starts can still bind every interface.
    lines += ["(deny network-outbound)",
              '(allow network-outbound (remote ip "localhost:*"))',
              '(allow network-outbound (remote tcp "*:443"))',
              '(allow network-outbound (literal "/private/var/run/mDNSResponder"))']
    # Local sockets inside the copy and the private temp folder (a test database, a language server).
    lines += [f"(allow network-outbound (remote unix-socket (subpath {sb_quote(p)})))" for p in (workdir, private_tmp)]
    return "\n".join(lines) + "\n"


def tools_section(workdir):
    heavy = HERE / "heavy.py"
    browse = browse_script()
    lines = ["", "## Your tools", "",
             f"Working copy: {workdir} (yours alone; nothing you change here reaches the real project).",
             f"Heavy commands (test suites, builds, typechecks, simulators): `python3 {heavy} run -- <command>`; "
             f"servers: `python3 {heavy} serve -- <command>` in the background. BUSY means another heavy job is "
             "running: wait and retry, never work around it."]
    if browse:
        lines.append(f"Browser: `python3 {browse} --root {workdir} <url> [steps]`, a fresh headless browser per call. "
                     "Steps run in order: --wait <ms>, --wait-for <sel>, --click <sel>, --hover <sel>, --fill <sel>=<text>, "
                     "--press <key>, --select <sel>=<value>, --check <sel>, --goto <url>, --eval <js>, --screenshot f.png, "
                     "--text f.txt, --html f.html, --snapshot f.yml (accessibility tree), --requests f.json (every request "
                     "with its status), --save-state f.json and --load-state f.json (carry a login between calls), "
                     "--viewport WxH. It prints one JSON line (blocked requests, console errors and warnings, page "
                     "errors, eval results). Only localhost and files inside the copy open.")
    lines.append("Run each of these as its own command, never chained with other commands: a chained command "
                 "stays inside the sandbox, where the browser cannot start.")
    lines.append("Your own temp folder is in $CHECKER_TMP. Folders that already existed in the shared temp folder "
                 "are hidden from you; a tool that fails on one (a fixed-name cache or temp folder) can be pointed at "
                 "$CHECKER_TMP instead, and that failure is not the product's.")
    protocols, stacks = protocols_dir(), stacks_dir()
    if protocols:
        lines.append(f"Any user interface: {protocols}/interface-baseline.md (the clarity pass). "
                     f"Validation protocols (read the one that fits the product): {protocols}/ui-ux-validation-protocol.md "
                     f"(web UI), native-ui-validation-protocol.md (native apps), game-qa-protocol.md (games), "
                     f"regression-and-coverage-strategy.md.")
    if stacks:
        lines.append(f"Stack packs: {stacks}/<name>.md (the pack named above, when one is).")
    return "\n".join(lines) + "\n"


def parse_args(argv):
    opts = {"deny": [], "canary": [], "allow_read": [], "network": [], "family": "claude", "effort": "xhigh",
            "timeout": "3000"}
    i = 0
    while i < len(argv):
        k = argv[i]
        if k == "--dry-run":
            opts["dry_run"] = True
            i += 1
        elif k == "--render":
            end = argv.index("--", i + 1) if "--" in argv[i + 1:] else len(argv)
            opts["render"] = argv[i + 1:end]
            i = end + 1
        elif k in ("--deny", "--canary", "--allow-read", "--network") and i + 1 < len(argv):
            opts[k[2:].replace("-", "_")].append(argv[i + 1])
            i += 2
        elif k in ("--dir", "--pack", "--out", "--family", "--effort", "--resume", "--agent-file", "--timeout",
                   "--project", "--mode") and i + 1 < len(argv):
            opts[k[2:].replace("-", "_")] = argv[i + 1]
            i += 2
        else:
            raise SystemExit(f"run_isolated: unknown or incomplete option {k}")
    if opts["family"] not in ("claude", "codex", "auto"):
        raise SystemExit("run_isolated: --family is claude, codex, or auto")
    return opts


def claude_cmd(role, opts, workdir, stem, sid):
    cfg_path = Path(str(stem) + ".settings.json")
    private_tmp = private_tmp_dir()
    cfg_path.write_text(json.dumps(settings(role, workdir, opts["deny"], opts.get("project"), opts["allow_read"],
                                            opts["network"], private_tmp), indent=2))
    agents_file = Path(str(stem) + ".agents.json")
    agent_path, agent_sha = agents_json(role, opts.get("agent_file"), agents_file)
    cmd = ["claude", "-p", "--agents", str(agents_file), "--agent", role, "--restricted",
           "--tools", ",".join(ROLES[role]), "--disable-slash-commands", "--strict-mcp-config",
           "--permission-mode", "dontAsk", "--settings", str(cfg_path),
           "--output-format", "stream-json", "--verbose", "--effort", opts["effort"]]
    stacks, protocols = stacks_dir(), protocols_dir()
    if role == "code-verifier":
        cmd += [x for d in (stacks, protocols) if d for x in ("--add-dir", str(d))]
    cmd += ["--resume", opts["resume"]] if opts.get("resume") else ["--session-id", sid]
    env = {k: v for k, v in os.environ.items() if k not in ("HEAVY_LOCK_HELD", "HEAVY_OWNER", "CODEX_THREAD_ID")}
    env["CLAUDE_CODE_TMPDIR"] = str(private_tmp)
    env["TMPDIR"] = str(private_tmp)  # the inherited one is under /var/folders, which the sandbox denies
    # Inside its sandbox Claude Code points TMPDIR at the shared per-user temp root, where every folder that existed
    # at launch is hidden (other sessions' files). pytest's fixed-name pytest-of-<user> is one of them, so its temp
    # root moves to this run's own folder.
    env["PYTEST_DEBUG_TEMPROOT"] = str(private_tmp)
    env["CHECKER_TMP"] = str(private_tmp)
    return cmd, env, {"agent_file": str(agent_path), "agent_sha256": agent_sha, "private_tmp": str(private_tmp)}


def codex_cmd(role, opts, workdir, stem, sid):
    codex = shutil.which("codex")
    if not codex:
        return None, None, {"unavailable": "codex is not installed"}
    codex = str(Path(codex).resolve())
    home = HOME / ".gate-copies" / f"codex-home-{secrets.token_hex(6)}"
    home.mkdir(parents=True, mode=0o700)
    if (HOME / ".codex/auth.json").exists():
        (home / "auth.json").symlink_to(HOME / ".codex/auth.json")
    private_tmp = private_tmp_dir()
    profile = Path(str(stem) + ".sb")
    profile.write_text(codex_profile(workdir, home, opts["allow_read"], private_tmp, codex))
    cmd = ["sandbox-exec", "-f", str(profile), codex, "exec", "-C", str(workdir), "-s", "danger-full-access",
           "--skip-git-repo-check", "-m", "gpt-6-astra", "-c", f'model_reasoning_effort="{opts["effort"]}"',
           "-c", 'approval_policy="never"', "--json", "-o", str(private_tmp / "result.md"), "-"]
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HEAVY_LOCK_HELD", "CLAUDECODE",
                        "CLAUDE_PROJECT_DIR")}
    env.update({"CODEX_HOME": str(home), "HEAVY_OWNER": f"codex-{sid}", "TMPDIR": str(private_tmp),
                "PYTEST_DEBUG_TEMPROOT": str(private_tmp), "CHECKER_TMP": str(private_tmp)})
    agent_path, meta, body = read_agent(role, opts.get("agent_file"))
    return cmd, env, {"agent_file": str(agent_path), "codex_home": str(home), "prefix": body + "\n\n",
                      "owner": f"codex-{sid}", "private_tmp": str(private_tmp),
                      "last_message": str(private_tmp / "result.md")}


def run_once(role, family, opts, workdir, stem, pack):
    sid = str(uuid.uuid4())
    result_path = Path(str(stem) + ".result.md")
    result_path.unlink(missing_ok=True)  # an earlier attempt's result must never stand in for this one
    if family == "codex":
        cmd, env, extra = codex_cmd(role, opts, workdir, stem, sid)
        if cmd is None:
            return {"status": "UNAVAILABLE", "reason": extra["unavailable"], "family": "codex"}
        stdin = extra.pop("prefix") + pack
    else:
        cmd, env, extra = claude_cmd(role, opts, workdir, stem, sid)
        stdin = pack
    if opts.get("dry_run"):
        extra.pop("last_message", None)
        for key in ("codex_home", "private_tmp"):
            if extra.get(key):
                shutil.rmtree(extra[key], ignore_errors=True)
        return {"status": "DRY_RUN", "cmd": cmd, "cwd": str(workdir), "stdin_chars": len(stdin), "family": family,
                "env_session_id_passed": "CLAUDE_CODE_SESSION_ID" in env, "env_codex_thread_passed": "CODEX_THREAD_ID" in env,
                "env_heavy_owner": env.get("HEAVY_OWNER"), "env_claude_tmpdir": "CLAUDE_CODE_TMPDIR" in env,
                **{k: v for k, v in extra.items() if k != "prefix"}}
    try:
        return launch(role, family, opts, workdir, stem, cmd, env, extra, stdin, sid, result_path)
    finally:
        # Also when the run is stopped (the gate stops a round's process group): no private folder is left behind
        # and no lease stays held.
        owner = extra.get("owner") or opts.get("resume") or sid
        subprocess.run([sys.executable, str(HERE / "heavy.py"), "release", "--owner", owner], capture_output=True)
        for key in ("codex_home", "private_tmp"):
            if extra.get(key):
                shutil.rmtree(extra[key], ignore_errors=True)


def launch(role, family, opts, workdir, stem, cmd, env, extra, stdin, sid, result_path):
    if shutil.which(cmd[0]) is None:
        return {"status": "ERROR", "reason": f"{cmd[0]} is not installed", "family": family}
    try:
        proc = subprocess.run(cmd, cwd=workdir, input=stdin, capture_output=True, text=True, env=env,
                              timeout=int(opts["timeout"]))
        stream, code, err = proc.stdout, proc.returncode, proc.stderr
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or ""
        stream, code, err = (raw.decode() if isinstance(raw, bytes) else raw), -1, "timeout"
    Path(str(stem) + ".jsonl").write_text(stream)
    info = parse_codex_stream(stream.splitlines()) if family == "codex" else parse_claude_stream(stream.splitlines())
    last = Path(extra.pop("last_message", "") or "/nonexistent")
    if family == "codex" and last.is_file():
        info["result"] = last.read_text()
        result_path.write_text(info["result"])
    elif info["result"] is not None:
        result_path.write_text(info["result"])
    canary_hits = [c for c in opts["canary"] if c in stream or c in (info["result"] or "")]
    reason = codex_unavailable(info, err) if family == "codex" and (code != 0 or info.get("errors")) else None
    if family == "codex" and not reason and code in (126, 127) and info["result"] is None:
        reason = "codex could not start: " + (err or "").strip()[-200:]
    if canary_hits:
        status = "LEAK"
    elif reason:
        status = "UNAVAILABLE"
    elif code != 0 or info["result"] is None or info.get("is_error"):
        status = "ERROR"
    elif info["tool_uses"] < (0 if opts.get("resume") else MIN_TOOLS[role]):
        status = "INCONCLUSIVE"
    else:
        status = "OK"
    return {"status": status, "family": family, "exit_code": code, "session_id": info["session_id"] or sid,
            "model": info["model"], "tool_uses": info["tool_uses"], "turns": info["turns"],
            "denials": info["denials"], "tools_seen": info.get("tools_seen"), "canary_hits": canary_hits,
            "unavailable_reason": reason, "errors": info.get("errors"), "stderr_tail": (err or "")[-400:],
            "agent_file": extra.get("agent_file"), "agent_sha256": extra.get("agent_sha256"),
            "confinement": "sandbox-exec profile (reads fenced to the copy and toolchains)" if family == "codex"
            else "claude --restricted + OS sandbox"}


def sweep_stale(hours=6):
    """Remove private folders left by runs that were killed outright (a run lasts at most its timeout)."""
    base = HOME / ".gate-copies"
    cutoff = time.time() - hours * 3600
    for d in list(base.glob("tmp-*")) + list(base.glob("codex-home-*")) if base.is_dir() else []:
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


def main(argv):
    if not argv or argv[0] not in ROLES:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda signum, frame: sys.exit(128 + signum))
    sweep_stale()
    role = argv[0]
    try:
        opts = parse_args(argv[1:])
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    if "dir" not in opts or "out" not in opts or ("pack" not in opts and "render" not in opts):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if opts["family"] != "claude" and role != "code-verifier":
        print("run_isolated: the Codex family is used only for code-verifier", file=sys.stderr)
        return 2
    auto_dir = opts["dir"] == "auto"
    if auto_dir:
        opts["dir"] = str(private_tmp_dir())
    workdir = Path(opts["dir"]).resolve()
    out = Path(opts["out"])
    out.mkdir(parents=True, exist_ok=True)
    render = opts.get("render") or []
    pass_no = render[render.index("--pass") + 1] if "--pass" in render[:-1] else None
    suffix = ("-demo" if opts.get("mode") == "demo" else "") + \
        ((f"-pass{pass_no}" if pass_no and pass_no != "1" else "-pass2") if opts.get("resume") else "")
    stem = out / f"{role}{suffix}"
    pack_path = Path(str(stem) + ".pack.md")
    if "render" in opts:
        render = list(opts["render"])
        if "--project" not in render and opts.get("project"):
            render = ["--project", opts["project"], *render]
        r = subprocess.run([sys.executable, str(HERE / "render_pack.py"), role, *render, "--out", str(pack_path)],
                           capture_output=True, text=True)
        if r.returncode == 2 or not pack_path.exists():
            if auto_dir:
                shutil.rmtree(workdir, ignore_errors=True)
            print(f"run_isolated: pack not rendered: {r.stderr.strip()[:400]}", file=sys.stderr)
            return 1
    else:
        shutil.copyfile(opts["pack"], pack_path)
    pack = pack_path.read_text(encoding="utf-8")
    if "Bash" in ROLES[role]:
        pack += tools_section(workdir)
        pack_path.write_text(pack, encoding="utf-8")
    pack_sha = hashlib.sha256(pack.encode()).hexdigest()

    missing = re.findall(r"^- (.+)$", pack.split("Missing inputs:", 1)[1], flags=re.M) if "Missing inputs:" in pack else []
    missing = [m for m in missing if m.strip() != "none"]

    def finish(summary):
        summary.update({"role": role, "mode": opts.get("mode") or "review", "pack_sha256": pack_sha,
                        "workdir": str(workdir), "pack_missing": missing})
        if auto_dir:
            shutil.rmtree(workdir, ignore_errors=True)
        Path(str(stem) + ".summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return 0 if summary["status"] in ("OK", "DRY_RUN") else 1

    if role == "loyal-evaluator" and not opts.get("resume"):
        leaks = pack_leaks(pack, opts.get("project"))
        if leaks:
            return finish({"status": "LEAK", "reason": "the pass-1 pack carries intent phrases", "phrases": leaks[:10]})
    servers = project_servers(opts.get("project")) if not opts.get("dry_run") else []
    if servers:
        return finish({"status": "BLOCKED", "reason": "a server started from the real project is listening; "
                       "stop it before the gate", "servers": servers})
    if opts["family"] in ("codex", "auto") and opts["network"]:
        # The Codex fence can only open ports, not hosts (its own model call needs HTTPS to anywhere), so a
        # project that names network hosts is reviewed where the fence holds to exactly those hosts.
        second = run_once(role, "claude", opts, workdir, stem, pack)
        second["family_switch"] = {"from": "codex", "to": "claude", "reason": "the project names Gate network hosts, "
                                   "which only the Claude sandbox can limit by host"}
        return finish(second)
    if opts["family"] in ("codex", "auto"):
        first = run_once(role, "codex", opts, workdir, stem, pack)
        if first["status"] == "UNAVAILABLE" and opts["family"] == "auto":
            second = run_once(role, "claude", opts, workdir, stem, pack)
            second["family_switch"] = {"from": "codex", "to": "claude",
                                       "reason": first.get("unavailable_reason") or first.get("reason")}
            return finish(second)
        return finish(first)
    return finish(run_once(role, "claude", opts, workdir, stem, pack))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
