#!/usr/bin/env python3
"""After a compaction, block writes to the project until the build record has been re-read.

Three modes, one per hook event:
  reload-gate.py arm    SessionStart, matcher "compact": inject the re-read directive and arm the gate
  reload-gate.py track  PostToolUse, matcher "Read|Bash": record which required files were read (the Read
                        tool, or a read-only shell command that prints the file: cat, head, tail, less, more,
                        bat, nl, or sed -n; ls, grep, or wc naming it does not show its content)
  reload-gate.py guard  PreToolUse, matcher "Write|Edit|MultiEdit|NotebookEdit|Bash" (Codex: "apply_patch|Bash",
                        the patch's file headers give the targets): while any required
                        file is unread, deny file edits inside the project and every shell command that is
                        not read-only (a redirection, sed -i, tee, mv, rm, a script run, a command
                        substitution, and the like). A command is split at its unquoted separators only, so a
                        quoted grep alternation is one read; git may take -C <dir> or --no-pager; the
                        pipeline's own `continuity.py recover` only prints and counts as a read

The project is $CLAUDE_PROJECT_DIR, else the nearest folder above the hook's cwd holding
docs/project/state.md, so a cd does not disarm the gate. Only such projects are affected. The required files
are whichever of docs/project/state.md, intent.md, and milestones.md exist. State lives per project and
session in ~/.claude/.reload-state/<project key>.<session>.project-needs (next to helm's own truth/ gate,
which is separate and unchanged). The conversation summary is lossy; the files are not.
On an internal error the hook allows the call and says so in a visible message.
"""
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/_shared/scripts"))
from project_policy import managed, hook_project, read as policy, control_command  # noqa: E402

REQUIRED = ("state.md", "intent.md", "milestones.md")
READ_ONLY = {"cat", "head", "tail", "less", "more", "bat", "sed", "awk", "grep", "rg", "ls", "find", "wc", "pwd",
             "echo", "stat", "file", "diff", "tree", "jq", "sort", "uniq", "cut", "git", "true"}
GIT_READ = {"status", "diff", "log", "show", "blame", "ls-files", "rev-parse", "branch"}
PRINTERS = {"cat", "head", "tail", "less", "more", "bat", "nl"}


def state_dir():
    d = Path(os.environ.get("RELOAD_STATE_DIR") or Path.home() / ".claude/.reload-state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_root(cwd):
    return hook_project({"cwd": cwd})


def patch_targets(tool_input):
    """File paths named in a Codex apply_patch payload (Codex puts the patch in tool_input.command)."""
    text = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
    if not isinstance(text, str):
        return []
    return re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$", text, flags=re.M)


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/_shared/scripts"
GIT_GLOBAL = {"-C": 2, "--no-pager": 1, "-P": 1}  # options before the subcommand that only choose where and how to show
BRANCH_WRITE_SHORT = set("dDmMcCfut")  # git branch's short options that change a branch or its config
BRANCH_WRITE_LONG = ("--delete", "--move", "--copy", "--force", "--set-upstream-to", "--unset-upstream",
                     "--edit-description", "--track", "--no-track", "--create-reflog", "--recurse-submodules")
# Short options of read programs that write: sort -o and tree -o name an output file, tree -R writes index pages,
# sed -i and -I edit in place. A cluster such as -ro or -ni holds them too.
WRITING_SHORT = {"sort": set("o"), "tree": set("oR"), "sed": set("iI"), "awk": set("opd")}
BRANCH_VALUE = {"--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--sort", "--format"}


class Unclear(Exception):
    """The shell would read this command differently from the scan, or it hides what it runs."""


def closing(command, i, opener):
    """The index just past the ) or ` that closes the substitution opened before i. A $( ... ) respects quotes and
    nesting; a backquote ends at the next unescaped backquote whatever quotes lie between, as the shell reads it."""
    depth, quote = 1, None
    while i < len(command):
        c = command[i]
        if opener == "`":
            if c == "\\":
                i += 1
            elif c == "`":
                return i + 1
        elif quote == "'":
            quote = None if c == "'" else quote
        elif c == "\\":
            i += 1
        elif quote == '"' and c == '"':
            quote = None
        elif not quote and c in "'\"":
            quote = c
        elif opener == "(" and not quote and c == "(":
            depth += 1
        elif opener == "(" and not quote and c == ")":
            depth -= 1
            if not depth:
                return i + 1
        i += 1
    raise Unclear("an unclosed substitution")


def scan(command):
    """Read a command as the shell would, as far as telling a read from a write needs: (its pieces between unquoted
    separators |, ||, &&, ;, &, newline; the commands its substitutions $(...), `...`, and <(...) run; whether it
    redirects output to a file). A | or > inside quotes belongs to its word; 2>&1, &>, and output thrown away to
    /dev/null are not writes. Raises Unclear for ANSI-C or locale quoting ($'...', $"..."), an unquoted comment (the
    shell ignores quotes after it), a here-document, an output process substitution >(...), an unclosed quote, any
    variable or parameter expansion outside single quotes (its value is unknown here: ${IFS} can split a word into a
    different command, zsh's ${(e)...} evaluates), and any other unquoted parenthesis (a subshell, a zsh glob
    qualifier such as *(e:...:) that runs code, zsh's =(...), an extended glob).
    Claude Code and Codex run commands in the user's shell, zsh here, so the scan refuses what either shell reads
    differently."""
    pieces, ends, inner, cur, quote, writes, i, redirect_at = [], [], [], [], None, False, 0, -1
    while i < len(command):
        c = command[i]
        if quote == "'":
            cur.append(c)
            quote = None if c == "'" else quote
        elif c == "\\" and command[i + 1:i + 2] == "\n":
            i += 2  # a line continuation: the shell joins the lines, so the word goes on
            continue
        elif c == "\\" and i + 1 < len(command):
            cur += [c, command[i + 1]]
            i += 1
        elif quote == '"' and c == '"':
            cur.append(c)
            quote = None
        elif c in "$`" and (command[i + 1:i + 2] == "(" or c == "`"):
            if c == "$" and command[i + 2:i + 3] == "(":
                raise Unclear("arithmetic expansion")
            end = closing(command, i + (2 if c == "$" else 1), "(" if c == "$" else "`")
            body = command[i + (2 if c == "$" else 1):end - 1]
            # inside backquotes the shell first removes a backslash before $, `, or \ (a nested backquote runs)
            inner.append(re.sub(r"\\([$`\\])", r"\1", body) if c == "`" else body)
            cur.append(command[i:end])
            i = end
            continue
        elif c == "$" and command[i + 1:i + 2] in ("?", "#", "$", "!"):
            cur += [c, command[i + 1]]  # an exit status, a count, a process id: a number, nothing hides in it
            i += 1
        elif c == "$" and re.match(r"[{\[\w@*-]", command[i + 1:i + 2]):
            raise Unclear("a variable or arithmetic expansion")
        elif c == "$" and not quote and command[i + 1:i + 2] in ("'", '"'):
            raise Unclear("ANSI-C or locale quoting")
        elif quote == '"':
            cur.append(c)
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c == "#" and (not cur or cur[-1].isspace()):
            raise Unclear("a comment")
        elif c == "<" and command[i + 1:i + 2] == "(":
            end = closing(command, i + 2, "(")
            inner.append(command[i + 2:end - 1])
            cur.append(command[i:end])
            i = end
            continue
        elif c == "<" and command[i + 1:i + 2] == "<":
            raise Unclear("a here-document")
        elif c in "()":
            raise Unclear("an unquoted parenthesis")
        elif c == "@" and re.match(r"@\{[\w.:/-]*\}", command[i:]) and ".." not in command[i:i + 40].split("}")[0]:
            m = re.match(r"@\{[\w.:/-]*\}", command[i:])
            cur += list(m.group(0))  # a git revision such as HEAD@{1} or @{u}: one item, never brace-expanded
            i += len(m.group(0))
            continue
        elif c in "{}":
            raise Unclear("an unquoted brace (a brace expansion turns one word into several)")
        elif c == ">":
            rest = command[i:]
            if rest.startswith(">("):
                raise Unclear("an output process substitution")
            if not re.match(r">>?\s*/dev/null(?=\s|$|[;&|)])|>&(\d+|-)(?=\s|$|[;&|<>)])", rest):
                writes = True
            cur.append(c)
            redirect_at = len(cur)
        elif c == "<":
            cur.append(c)
            redirect_at = len(cur)
        elif c == "&" and ((cur and len(cur) == redirect_at) or command[i + 1:i + 2] == ">"):
            cur.append(c)  # part of a redirection (2>&1, <&3, &>); an escaped \> before & is a character
        elif c in "|;&\n":
            pieces.append("".join(cur))
            ends.append(c)
            cur = []
        else:
            cur.append(c)
        i += 1
    if quote:
        raise Unclear("an unclosed quote")
    pieces.append("".join(cur))
    ends.append("")
    PIPED.clear()
    PIPED.extend(e == "|" for s, e in zip(pieces, ends) if s.strip())
    return [s.strip() for s in pieces if s.strip()], inner, writes


PIPED = []  # for the last scan: whether each piece's output goes into the next piece


def pipelines(command):
    """The pieces of a command grouped into pipelines ([[cat x, wc -l], [ls]]), or [] when it cannot be read."""
    try:
        pieces = scan(command)[0]
    except Unclear:
        return []
    groups, group = [], []
    for piece, piped in zip(pieces, list(PIPED)):
        group.append(piece)
        if not piped:
            groups.append(group)
            group = []
    return groups + ([group] if group else [])


def shown(pipeline, k):
    """True when the output of piece k of a pipeline reaches the screen: not thrown away to /dev/null by it or a
    later piece, and not only counted (a later wc, or grep -c, -l, -q)."""
    for later in pipeline[k:]:
        if re.search(r"(^|\s)(1?>>?|&>)\s*/dev/null", later):
            return False
    for later in pipeline[k + 1:]:
        words = later.split()
        if words and (os.path.basename(words[0]) == "wc" or
                      (os.path.basename(words[0]) in ("grep", "rg") and any(w in ("-c", "-l", "-q", "--count",
                                                                                   "--quiet", "--files-with-matches")
                                                                            for w in words[1:]))):
            return False
    return True


def segments(command):
    """The pieces of a shell command between its unquoted separators; [] when it cannot be read with certainty."""
    try:
        return scan(command)[0]
    except Unclear:
        return []


def pipeline_read(words):
    """`python3 <the pipeline's own continuity.py> recover <dir>`: the recovery step prints and writes nothing. The
    interpreter is named plainly (a bare name, a system bin path, or this very interpreter), never ./python3."""
    interpreter = words[0] if words and words[0] == sys.executable else program_name(words[0]) if words else None
    if interpreter and re.fullmatch(r"python(?:3(?:\.\d+)?)?", os.path.basename(interpreter)):
        words = words[1:]
    if len(words) != 3 or words[1] != "recover":
        return False
    try:
        # This very file, not a copy: a copy elsewhere would import whatever modules sit beside it.
        return Path(words[0]).expanduser().resolve() == (SCRIPTS / "continuity.py").resolve()
    except (OSError, RuntimeError, ValueError):  # ~user names no one, a NUL in a path: never a read
        return False


# Options of otherwise read-only programs that run a command or write a file.
RUNS_OR_WRITES = {"rg": ("--pre",), "sort": ("--compress-program", "--output"), "bat": ("--pager", "cache"),
                  "less": ("+", "-o", "-O", "--log-file", "--LOG-FILE", "-k", "--lesskey"),
                  "more": ("+",), "file": ("-C", "--compile"), "tree": ("-R",),
                  "awk": ("-o", "-p", "-d", "--pretty-print", "--profile", "--dump-variables")}
SYSTEM_BIN = re.compile(r"/(usr/(local/)?)?s?bin/[\w.+-]+|/opt/homebrew/bin/[\w.+-]+")


def program_name(word):
    """The program a command word runs when it names one plainly (a bare name, or an absolute path in a system bin
    folder), else None: ./cat or a word built from an expansion may run anything."""
    if re.fullmatch(r"[\w.+-]+", word):
        return word
    return os.path.basename(word) if SYSTEM_BIN.fullmatch(word) else None


def short_letters(word):
    """The letters of a short option cluster (-ro gives r and o), or an empty set for anything else."""
    return set(word[1:]) if len(word) > 1 and word[0] == "-" and word[1] != "-" else set()


def long_option(word, names):
    """The long option among names that word spells or abbreviates (GNU tools accept any unambiguous start, so
    --out is --output), or None."""
    name = word.split("=", 1)[0]
    if not name.startswith("--") or len(name) < 3:
        return None
    return next((n for n in names if n.startswith("--") and n.startswith(name)), None)


def program_text(words, file_flags, expr_flags, value_flags=()):
    """The script a sed or awk command runs (its expression options, else its first operand after the options and
    their values), or None when part of it comes from a file or a library and cannot be read here. Short options
    may be clustered (-ne 'p' is -n -e 'p'; -nf x reads a file) and take their value attached or as the next word;
    long ones may be abbreviated."""
    shorts = {f[1]: kind for kind, fl in (("file", file_flags), ("expr", expr_flags), ("value", value_flags))
              for f in fl if len(f) == 2 and f[0] == "-"}
    longs = {f: kind for kind, fl in (("file", file_flags), ("expr", expr_flags), ("value", value_flags))
             for f in fl if f.startswith("--")}
    args, scripts, operands, i = words[1:], [], [], 0
    while i < len(args):
        w = args[i]
        if w == "--":
            operands += args[i + 1:]
            break
        if w.startswith("--"):
            name = long_option(w, longs)
            kind = longs.get(name)
            value = w.split("=", 1)[1] if "=" in w else (args[i + 1] if i + 1 < len(args) else "")
            step = 1 if "=" in w else 2
            if kind == "file":
                return None
            if kind == "expr":
                scripts.append(value)
                i += step
                continue
            i += step if kind == "value" else 1
            continue
        if w.startswith("-") and len(w) > 1:
            for k, letter in enumerate(w[1:], 1):
                kind = shorts.get(letter)
                if not kind:
                    continue
                attached = w[k + 1:]
                value = attached or (args[i + 1] if i + 1 < len(args) else "")
                if kind == "file":
                    return None
                if kind == "expr":
                    scripts.append(value)
                if not attached:
                    i += 1  # the value is the next word
                break
            i += 1
            continue
        operands.append(w)
        i += 1
    if scripts:
        return "\n".join(scripts)
    return operands[0] if operands else ""


def sed_reads(script):
    """True when a sed script only prints: commands separated by ; or newlines, each an optional address (a line
    number, $, or /regex/, or a range of two) with an optional !, then p d n N g G h H x l = or q, a { } block of
    such commands, or s<d>...<d>...<d> with flags from g p i I m and digits. Anything else (w, W, e, r, a, i, c, y,
    another address form, a comment) is not known to be a read."""
    i, n, depth = 0, len(script), 0

    def regex(j, delim):
        while j < n and script[j] != delim:
            if script[j] == "\\":
                j += 1
            elif script[j] == "[":
                k = j + 1
                k += script[k:k + 1] == "^"
                k += script[k:k + 1] == "]"  # a ] first in the bracket is a character, not its end
                end = script.find("]", k)
                if end < 0 or re.search(r"\[[:.=]", script[j + 1:end + 1]):
                    return -1  # a class like [:alpha:] has its own ]; such a bracket is not read here
                j = end
            elif script[j] == "\n":
                return -1
            j += 1
        return j + 1 if j < n else -1

    def address(j):
        if j < n and script[j].isdigit():
            while j < n and script[j].isdigit():
                j += 1
            return j
        if j < n and script[j] == "$":
            return j + 1
        if j < n and script[j] == "/":
            k = regex(j + 1, "/")
            while 0 < k < n and script[k] in "IM":
                k += 1
            return k
        return j

    while i < n:
        c = script[i]
        if c in " \t;\n":
            i += 1
            continue
        if c == "}":
            depth -= 1
            if depth < 0:
                return False
            i += 1
            continue
        j = address(i)
        if j < 0:
            return False
        if j > i:
            k = j
            while k < n and script[k] in " \t":
                k += 1
            if k < n and script[k] == ",":
                k += 1
                while k < n and script[k] in " \t":
                    k += 1
                e = address(k)
                if e < 0 or e == k:
                    return False
                j = e
        while j < n and script[j] in " \t!":
            j += 1
        if j >= n:
            return False
        c = script[j]
        if c == "{":
            depth += 1
            i = j + 1
            continue
        if c in "pdnNgGhHxl=":
            i = j + 1
        elif c == "q":
            i = j + 1
            while i < n and script[i].isdigit():
                i += 1
        elif c == "s" and j + 1 < n and script[j + 1] not in "\\\n":
            d = script[j + 1]
            k = regex(j + 2, d)
            k = regex(k, d) if k > 0 else -1
            if k < 0:
                return False
            while k < n and script[k] in "gpiIm0123456789":
                k += 1
            i = k
        else:
            return False
        while i < n and script[i] in " \t":
            i += 1
        if i < n and script[i] not in ";\n}":
            return False
    return depth == 0


def program_writes(head, words):
    """True when sed or awk would write a file or run a command, or might (a script that is not a plain printing
    sed script; awk's system(), getline, a pipe, a print redirected to a file, @load, or code from a file), and any
    writing short option, alone or in a cluster."""
    if any(short_letters(w) & WRITING_SHORT.get(head, set()) for w in words[1:]):
        return True
    if head == "sed":
        script = program_text(words, ("-f", "--file"), ("-e", "--expression"), ("-l",))
        return script is None or not sed_reads(script)
    if head == "awk":
        script = program_text(words, ("-f", "--file", "-E", "--exec", "-l", "--load", "-i", "--include"),
                              ("-e", "--source"), ("-F", "-v"))
        # any > at all: telling a comparison from a print to a file needs awk's own parser (a string can hold ; or })
        if script is None or re.search(r"system\s*\(|getline|\||>|@load", script):
            return True
    flags = RUNS_OR_WRITES.get(head, ())
    return any(w == flag or w.startswith(flag) or long_option(w, flags) for w in words[1:] for flag in flags)


def git_reads(words, root=None, cwd=None):
    """True for a git command that only shows: --no-pager allowed, and -C <dir> only into the project itself (another
    folder's git config can name a command for git to run, such as core.fsmonitor), -c (which can set a command to
    run) never; a read subcommand; no --output file; a branch listing, never a branch change."""
    rest = words[1:]
    while rest and rest[0] in GIT_GLOBAL:
        if rest[0] == "-C":
            if len(rest) < 2 or root is None:
                return False
            target = Path(cwd or ".") / Path(rest[1]).expanduser()
            try:
                target = target.resolve()
                if target != Path(root).resolve() and not target.is_relative_to(Path(root).resolve()):
                    return False
            except (OSError, RuntimeError, ValueError):
                return False
        rest = rest[GIT_GLOBAL[rest[0]]:]
    if not rest or rest[0] not in GIT_READ or any(w.startswith("--output") for w in rest):
        return False
    if rest[0] == "branch":
        args = rest[1:]
        for w in args:
            name = w.split("=", 1)[0]
            if short_letters(w) & BRANCH_WRITE_SHORT or (len(name) > 2 and name.startswith("--") and
                                                        any(f.startswith(name) for f in BRANCH_WRITE_LONG)):
                return False  # git takes any unambiguous start of a long option, so --unset-up is --unset-upstream
        listing = "--list" in args or "-l" in args
        for i, w in enumerate(args):
            if not w.startswith("-") and not listing and not (i and args[i - 1] in BRANCH_VALUE):
                return False  # git branch <name> creates one
    return True


def read_only(command, depth=0, root=None, cwd=None):
    """True when every piece of a shell command only reads, and so does every command its substitutions run."""
    try:
        pieces, inner, writes = scan(command)
    except Unclear:
        return False
    if writes or depth > 4 or not all(read_only(c, depth + 1, root, cwd) for c in inner):
        return False
    for seg in pieces:
        try:
            words = shlex.split(seg)
        except ValueError:
            return False
        if not words:
            continue
        if pipeline_read(words):
            continue
        head = program_name(words[0])
        if head not in READ_ONLY or program_writes(head, words):
            return False
        if head == "sed" and any(long_option(w, ("--in-place",)) for w in words[1:]):
            return False
        if head == "find" and any(w in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0",
                                        "-fprintf", "-fls") for w in words[1:]):
            return False
        if head in ("sort", "tree") and any(w == "-o" or w.startswith(("-o", "--output")) for w in words[1:]):
            return False
        if head == "uniq" and len([w for w in words[1:] if not w.startswith("-")]) >= 2:
            return False  # uniq <input> <output> writes the output file
        if head == "git" and not git_reads(words, root, cwd):
            return False
    return True


def prints(seg):
    """True when a read-only command segment shows file content (so naming a file in it means reading it)."""
    try:
        words = shlex.split(seg)
    except ValueError:
        return False
    if not words:
        return False
    head = os.path.basename(words[0])
    return head in PRINTERS or (head == "sed" and "-n" in words[1:])


def key(root, session):
    h = hashlib.sha1(str(root).encode()).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (session or "nosid"))
    return state_dir() / f"{h}.{safe}.project-needs"


def required(root):
    docs = root / "docs/project"
    return [str((docs / name).resolve()) for name in REQUIRED if (docs / name).is_file()]


def arm(data):
    root = project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not managed(root):
        return 0
    if not (root / "docs/project/state.md").is_file():
        return 0
    needs = required(root)
    key(root, data.get("session_id")).write_text(json.dumps({"needs": needs, "read": [], "policy": policy(root)["token"]}))
    snaps = sorted((root / ".evidence/compact").glob("*.md"))
    snap = f", and the snapshot {snaps[-1].relative_to(root)}" if snaps else ""
    listed = ", then ".join(str(Path(p).relative_to(root)) for p in needs)
    text = ("The conversation was just compacted, and the summary above is lossy. Before any further edit, "
            f"re-read {listed}, plus docs/project/brief.md and the tail of docs/project/decisions.md{snap}. "
            "Writes to this project are blocked until those three files have been read. Compare git status "
            "with state.md and say what differs. Anything with an ID (constraints C-, must-not-lose L-, "
            "decisions D-, findings) comes from the files, never from the summary. If a decision made before "
            "compaction is missing from decisions.md, write it once the files are read.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    return 0


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def track(data):
    root = project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not managed(root):
        return 0
    path = key(root, data.get("session_id"))
    record = load(path)
    if not record:
        return 0
    tool_input = data.get("tool_input") or {}
    targets = []
    if data.get("tool_name") == "Bash":
        command = tool_input.get("command", "")
        if read_only(command, root=root, cwd=data.get("cwd")):
            for seg in [s for line in pipelines(command) for k, s in enumerate(line) if shown(line, k)]:
                if not prints(seg):
                    continue
                for need in record["needs"]:
                    rel = str(Path(need).relative_to(root))
                    if need in seg or re.search(rf"(^|[\s'\"/]){re.escape(rel)}\b", seg):
                        targets.append(need)
    elif tool_input.get("file_path"):
        targets.append(str(Path(tool_input["file_path"]).expanduser().resolve()))
    for resolved in targets:
        if resolved in record["needs"] and resolved not in record["read"]:
            record["read"].append(resolved)
    if set(record["needs"]) <= set(record["read"]):
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(record))
    return 0


def guard(data):
    root = project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not managed(root) or control_command((data.get("tool_input") or {}).get("command", "")):
        return 0
    record = load(key(root, data.get("session_id")))
    if not record:
        return 0
    if record.get("policy") and record["policy"] != policy(root)["token"]:
        return 0
    remaining = [str(Path(p).relative_to(root)) for p in record["needs"] if p not in record["read"]]
    if not remaining:
        return 0
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") == "Bash":
        if read_only(tool_input.get("command", ""), root=root, cwd=data.get("cwd")):
            return 0
        what = "shell commands that change files"
    else:
        targets = patch_targets(tool_input) or [tool_input.get("file_path") or tool_input.get("notebook_path") or ""]
        if data.get("tool_name") == "apply_patch" and not any(targets):
            # A patch whose files cannot be read out of it may write anywhere: fail closed while armed.
            targets = [str(root)]
        inside = []
        for target in [t for t in targets if t]:
            path = Path(target).expanduser()
            path = path if path.is_absolute() else Path(data.get("cwd") or root) / path
            if not managed(path):
                continue
            try:
                path.resolve().relative_to(root)
                inside.append(target)
            except ValueError:
                continue
        if not inside:
            return 0
        what = "edits in this project"
    reason = (f"Blocked: {what} wait until the build record is re-read after compaction (the summary is "
              "lossy). Read these first (the Read tool, or cat): " + ", ".join(remaining) + ".")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def main(argv):
    if len(argv) != 1 or argv[0] not in ("arm", "track", "guard"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        return {"arm": arm, "track": track, "guard": guard}[argv[0]](data)
    except Exception as exc:
        print(json.dumps({"systemMessage": f"reload-gate {argv[0]} hit an internal error and allowed the call: "
                                           f"{exc.__class__.__name__}: {exc}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
