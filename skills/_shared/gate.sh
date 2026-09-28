#!/bin/bash
# gate.sh - deterministic rot/security gate for the coding pipeline.
# Run by /gate at each milestone (on the project itself: the review copy has no .git; the gate compares the
# product fingerprint before and after, so a lint --fix that edits the tree is a FAIL), and by /deploy at release. Every check prints PASS / FAIL / WARN / SKIP; a SKIP is named, never implied as
# a pass. Exit 0 = no FAIL. Exit 1 = at least one FAIL. Exit 2 = bad invocation.
# Usage: gate.sh [project-dir]                 the checks
#        gate.sh --fingerprint [project-dir]   print the product fingerprint and exit
#        gate.sh --inventory [project-dir]     list silent-degradation candidates and exit

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
MODE=check
case "${1:-}" in
  --fingerprint) MODE=fingerprint; shift ;;
  --inventory) MODE=inventory; shift ;;
  --*) echo "gate: unknown option ${1}" >&2; exit 2 ;;
esac

DIR="${1:-.}"
cd "$DIR" 2>/dev/null || { echo "gate: cannot cd to $DIR" >&2; exit 2; }

if [ "$MODE" = fingerprint ]; then
  exec python3 "$HERE/scripts/fingerprint.py" .
fi
if [ "$MODE" = inventory ]; then
  exec python3 "$HERE/scripts/inventory.py" .
fi

FAILS=0
WARNS=0

report() {
  printf '%-5s  %-16s  %s\n' "$1" "$2" "$3"
  case "$1" in
    FAIL) FAILS=$((FAILS + 1)) ;;
    WARN) WARNS=$((WARNS + 1)) ;;
  esac
}

EX="--exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist --exclude-dir=build
    --exclude-dir=.next --exclude-dir=out --exclude-dir=target --exclude-dir=vendor
    --exclude-dir=.venv --exclude-dir=venv --exclude-dir=coverage --exclude-dir=__pycache__
    --exclude-dir=.evidence
    --exclude=*.min.js --exclude=*.map --exclude=*.lock --exclude=package-lock.json
    --exclude=gate.sh"
# project-specific exclusions from docs/project/gate.md ("Gate exclude: a, b"); single names only, since grep
# matches --exclude-dir against folder names, not paths
for x in $(python3 "$HERE/scripts/gate_keys.py" . --json 2>/dev/null | python3 -c 'import json,sys; print(" ".join(e.rstrip("/") for e in json.load(sys.stdin).get("Gate exclude", []) if "/" not in e.rstrip("/")))' 2>/dev/null); do
  EX="$EX --exclude-dir=$x --exclude=$x"
done

echo "== gate: $(pwd) =="
echo

# ---- secrets ---------------------------------------------------------------
if command -v gitleaks >/dev/null 2>&1 && [ -d .git ]; then
  if gitleaks detect --no-banner --source . >/dev/null 2>&1; then
    report PASS secrets "gitleaks clean"
  else
    report FAIL secrets "gitleaks found leaks (run: gitleaks detect --source .)"
  fi
else
  HITS=$(grep -rIlE $EX \
    -e '-----BEGIN (RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY' \
    -e 'AKIA[0-9A-Z]{16}' \
    -e 'ghp_[A-Za-z0-9]{36}' \
    -e 'gho_[A-Za-z0-9]{36}' \
    -e 'github_pat_[A-Za-z0-9_]{22}' \
    -e 'xox[baprs]-[0-9A-Za-z-]{10}' \
    -e 'AIza[0-9A-Za-z_-]{35}' \
    -e 'sk-[A-Za-z0-9_-]{28}' \
    -e 'sk_(live|test)_[0-9A-Za-z]{20}' \
    . 2>/dev/null | head -5 | tr '\n' ' ')
  if [ -n "${HITS// /}" ]; then
    report FAIL secrets "credential-shaped strings in: $HITS"
  else
    report PASS secrets "pattern scan clean (gitleaks not installed; patterns only)"
  fi
fi

if [ -d .git ] && command -v git >/dev/null 2>&1; then
  ENVTRACKED=$(git ls-files 2>/dev/null | grep -E '(^|/)\.env(\.[A-Za-z0-9]+)?$' | grep -viE 'example|sample|template' | head -3 | tr '\n' ' ')
  if [ -n "${ENVTRACKED// /}" ]; then
    report FAIL env-files "tracked env file(s): $ENVTRACKED"
  else
    report PASS env-files "no tracked .env"
  fi
else
  report SKIP env-files "not a git repo"
fi

# ---- lint --------------------------------------------------------------------
LINTED=0
if [ -f package.json ] && grep -q '"lint"' package.json; then
  PM=npm
  [ -f pnpm-lock.yaml ] && PM=pnpm
  [ -f yarn.lock ] && PM=yarn
  [ -f bun.lockb ] && PM=bun
  if OUT=$($PM run lint 2>&1); then
    report PASS lint "$PM run lint clean"
  else
    report FAIL lint "$PM run lint failed: $(printf '%s\n' "$OUT" | tail -1)"
  fi
  LINTED=1
fi
if command -v ruff >/dev/null 2>&1; then
  if find . -name '*.py' -not -path './.venv/*' -not -path './venv/*' -not -path './node_modules/*' 2>/dev/null | head -1 | grep -q .; then
    if OUT=$(ruff check . 2>&1); then
      report PASS lint-py "ruff clean"
    else
      report FAIL lint-py "ruff: $(printf '%s\n' "$OUT" | tail -1)"
    fi
    LINTED=1
  fi
fi
if [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  if cargo clippy --version >/dev/null 2>&1; then
    if OUT=$(cargo clippy -q 2>&1); then
      report PASS lint-rs "clippy clean"
    else
      report FAIL lint-rs "clippy: $(printf '%s\n' "$OUT" | tail -1)"
    fi
  else
    report SKIP lint-rs "Cargo.toml present but clippy not installed"
  fi
  LINTED=1
fi
if [ -f go.mod ] && command -v go >/dev/null 2>&1; then
  if OUT=$(go vet ./... 2>&1); then
    report PASS lint-go "go vet clean"
  else
    report FAIL lint-go "go vet: $(printf '%s\n' "$OUT" | tail -1)"
  fi
  FMT=$(gofmt -l . 2>/dev/null | head -3 | tr '\n' ' ')
  if [ -n "${FMT// /}" ]; then
    report WARN gofmt "unformatted: $FMT"
  fi
  LINTED=1
fi
SWIFTPROJ=$(ls -d ./*.xcodeproj ./*.xcworkspace 2>/dev/null | head -1)
if [ -n "$SWIFTPROJ" ] || [ -f Package.swift ]; then
  SWIFTLINTED=0
  if command -v swiftformat >/dev/null 2>&1; then
    if OUT=$(swiftformat --lint . 2>&1); then
      report PASS fmt-swift "swiftformat clean"
    else
      report WARN fmt-swift "swiftformat: $(printf '%s\n' "$OUT" | tail -1)"
    fi
    SWIFTLINTED=1
  fi
  if command -v swiftlint >/dev/null 2>&1; then
    if OUT=$(swiftlint --quiet 2>&1); then
      report PASS lint-swift "swiftlint clean"
    else
      report FAIL lint-swift "swiftlint: $(printf '%s\n' "$OUT" | tail -1)"
    fi
    SWIFTLINTED=1
  fi
  if [ $SWIFTLINTED -eq 0 ]; then
    report SKIP lint-swift "Swift project present but neither swiftformat nor swiftlint installed"
  fi
  LINTED=1
fi
if [ $LINTED -eq 0 ]; then
  report SKIP lint "no recognized linter (npm lint script / ruff / clippy / go vet / swiftlint)"
fi

# ---- typecheck / build -------------------------------------------------------
BUILT=0
if [ -f tsconfig.json ]; then
  if npx --no-install tsc --version >/dev/null 2>&1; then
    if OUT=$(npx --no-install tsc --noEmit 2>&1); then
      report PASS typecheck "tsc --noEmit clean"
    else
      report FAIL typecheck "tsc: $(printf '%s\n' "$OUT" | grep 'error TS' | head -1)"
    fi
  else
    report SKIP typecheck "tsconfig.json present but typescript not installed locally"
  fi
  BUILT=1
fi
if [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  if OUT=$(cargo check -q 2>&1); then
    report PASS build-rs "cargo check clean"
  else
    report FAIL build-rs "cargo check: $(printf '%s\n' "$OUT" | tail -1)"
  fi
  BUILT=1
fi
if [ -f go.mod ] && command -v go >/dev/null 2>&1; then
  if OUT=$(go build ./... 2>&1); then
    report PASS build-go "go build clean"
  else
    report FAIL build-go "go build: $(printf '%s\n' "$OUT" | tail -1)"
  fi
  BUILT=1
fi
if [ -f Package.swift ] && [ -z "$SWIFTPROJ" ]; then
  # Pure SPM: xcodebuild exists on every Mac with Xcode, so this must be checked FIRST
  # or the swift-build path is unreachable.
  if command -v swift >/dev/null 2>&1; then
    if OUT=$(swift build 2>&1); then
      report PASS build-swift "swift build clean"
    else
      report FAIL build-swift "swift build: $(printf '%s\n' "$OUT" | tail -1)"
    fi
  else
    report SKIP build-swift "Package.swift present but swift not installed"
  fi
  BUILT=1
elif [ -n "$SWIFTPROJ" ]; then
  if command -v xcodebuild >/dev/null 2>&1; then
    # print the whole line, not $1: a scheme named "My App" would otherwise become "My"
    SCHEME=$(xcodebuild -list 2>/dev/null \
      | awk '/Schemes:/{f=1;next} f&&NF{sub(/^[ \t]+/,"");sub(/[ \t]+$/,"");print;exit}')
    if [ -n "$SCHEME" ]; then
      RAW=$(xcodebuild -scheme "$SCHEME" -destination 'generic/platform=iOS Simulator' \
              -quiet build 2>&1)
      RC=$?    # capture xcodebuild's own status; a pipeline would report tail's status (always 0)
      if [ $RC -eq 0 ]; then
        report PASS build-swift "xcodebuild $SCHEME succeeded"
      else
        LAST=$(printf '%s\n' "$RAW" | grep -E "error:" | tail -1)
        report FAIL build-swift "xcodebuild $SCHEME: ${LAST:-exit $RC, no error line}"
      fi
    else
      report SKIP build-swift "Swift project present but no scheme found via xcodebuild -list"
    fi
  else
    report SKIP build-swift "Swift project present but xcodebuild not available"
  fi
  BUILT=1
fi
if [ $BUILT -eq 0 ]; then
  report SKIP typecheck "no tsconfig.json / Cargo.toml / go.mod / Swift project"
fi

# ---- screenshot evidence freshness -------------------------------------------
# The documented rule (swift-ios.md, native-ui-validation-protocol.md) is: NO image may
# predate the newest source file. So compare against the OLDEST image; checking the newest
# lets one fresh capture launder a whole folder of stale ones, which is the exact
# captured-once-and-never-retaken failure this exists to catch.
EVDIR=""
for d in .evidence qa-evidence evidence screenshots; do
  [ -d "$d" ] && EVDIR="$d" && break
done
if [ -n "$EVDIR" ]; then
  OLDEST_SHOT=$(find "$EVDIR" -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' \
    -o -name '*.heic' \) -exec ls -t {} + 2>/dev/null | tail -1)
  if [ -z "$OLDEST_SHOT" ]; then
    report SKIP evidence-fresh "$EVDIR exists but holds no images"
  else
    # NOTE: $EX is grep syntax and must NOT be passed to find; doing so makes find fail
    # silently and the check reports clean. find needs -prune predicates instead. Keep this
    # list in step with $EX above.
    STALE=$(find . \( -name node_modules -o -name .git -o -name build -o -name dist \
      -o -name .build -o -name DerivedData -o -name target -o -name vendor -o -name Pods \
      -o -name .swiftpm -o -name Carthage -o -name .venv -o -name venv -o -name .next \
      -o -name out -o -name coverage -o -name __pycache__ -o -name "$EVDIR" \) -prune -o \
      -type f \( -name '*.swift' -o -name '*.ts' -o -name '*.tsx' \
      -o -name '*.js' -o -name '*.jsx' -o -name '*.kt' -o -name '*.py' \) \
      -newer "$OLDEST_SHOT" -print 2>/dev/null)
    N=$(printf '%s\n' "$STALE" | grep -c . )
    if [ "$N" -gt 0 ]; then
      report WARN evidence-fresh "$N source file(s) newer than the oldest capture; re-capture at the exit gate"
    else
      report PASS evidence-fresh "every capture postdates all source"
    fi
  fi
else
  report SKIP evidence-fresh "no evidence directory (.evidence/ etc.)"
fi

# ---- stack knowledge pack wired ----------------------------------------------
# The packs sat orphaned for months because loading was a soft instruction nobody checked.
# If a pack's detection matches this project, AGENTS.md must name it.
PACKS=~/.claude/skills/_shared/references/stacks
if [ -d "$PACKS" ]; then
  WANT=""
  [ -n "$SWIFTPROJ" ] || [ -f Package.swift ] && WANT=swift-ios
  [ -f go.mod ] && WANT=go
  [ -f Cargo.toml ] && WANT=rust
  if [ -n "$WANT" ] && [ -f "$PACKS/$WANT.md" ]; then
    if grep -qsE "^Stack pack: *[a-z]" docs/project/gate.md AGENTS.md; then
      report PASS stack-pack "a stack pack is named ($WANT detected)"
    else
      report WARN stack-pack "$WANT pack exists but docs/project/gate.md names no 'Stack pack:' (/plan writes it)"
    fi
  else
    report SKIP stack-pack "no stack pack matches this project"
  fi
fi

# ---- dependency audit --------------------------------------------------------
AUDITED=0
if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then
  if OUT=$(pnpm audit --prod --audit-level high 2>&1); then
    report PASS deps "pnpm audit clean (high+)"
  else
    report FAIL deps "pnpm audit: high+ vulnerabilities or audit error (re-run to see)"
  fi
  AUDITED=1
elif [ -f package-lock.json ] && command -v npm >/dev/null 2>&1; then
  if OUT=$(npm audit --omit=dev --audit-level=high 2>&1); then
    report PASS deps "npm audit clean (high+)"
  else
    report FAIL deps "npm audit: high+ vulnerabilities or audit error (re-run to see)"
  fi
  AUDITED=1
fi
if [ -f Cargo.lock ] && cargo audit --version >/dev/null 2>&1; then
  if OUT=$(cargo audit -q 2>&1); then
    report PASS deps-rs "cargo audit clean"
  else
    report FAIL deps-rs "cargo audit: $(printf '%s\n' "$OUT" | tail -1)"
  fi
  AUDITED=1
fi
if command -v pip-audit >/dev/null 2>&1; then
  if [ -f requirements.txt ] || [ -f pyproject.toml ]; then
    if OUT=$(pip-audit 2>&1); then
      report PASS deps-py "pip-audit clean"
    else
      report FAIL deps-py "pip-audit: $(printf '%s\n' "$OUT" | tail -1)"
    fi
    AUDITED=1
  fi
fi
if [ $AUDITED -eq 0 ]; then
  report SKIP deps "no lockfile+auditor pair (npm/pnpm audit, cargo audit, pip-audit)"
fi

# ---- leftover debug ------------------------------------------------------------
DBG=$(grep -rnE $EX --include='*.js' --include='*.jsx' --include='*.ts' --include='*.tsx' -e '^[[:space:]]*debugger[[:space:];]*$' . 2>/dev/null | head -3 | tr '\n' ' ')
PDB=$(grep -rnE $EX --include='*.py' -e 'pdb\.set_trace\(\)|breakpoint\(\)' . 2>/dev/null | head -3 | tr '\n' ' ')
if [ -n "${DBG// /}" ] || [ -n "${PDB// /}" ]; then
  report FAIL debug "debugger/breakpoint left in: $DBG$PDB"
else
  report PASS debug "no debugger/breakpoint statements"
fi
ONLY=$(grep -rnE $EX --include='*.test.*' --include='*.spec.*' -e '\.only\(' . 2>/dev/null | head -3 | tr '\n' ' ')
if [ -n "${ONLY// /}" ]; then
  report FAIL focused-tests ".only() narrows the suite: $ONLY"
else
  report PASS focused-tests "no .only() in tests"
fi
CLOG=$(grep -rE $EX --include='*.ts' --include='*.tsx' --include='*.jsx' -e 'console\.log' . 2>/dev/null | wc -l | tr -d ' ')
if [ "$CLOG" -gt 0 ]; then
  report WARN console-log "$CLOG console.log line(s) (legitimate for a CLI; noise elsewhere)"
else
  report PASS console-log "none"
fi
TODOS=$(grep -rIn $EX -e 'TODO' -e 'FIXME' . 2>/dev/null | wc -l | tr -d ' ')
if [ "$TODOS" -gt 0 ]; then
  report WARN todos "$TODOS TODO/FIXME line(s); none may sit on a load-bearing path"
else
  report PASS todos "none"
fi

# ---- placeholder lint (placeholder consent) -----------------------------------
# Product-path stand-ins need an explicit consent token; without one they FAIL.
# Precision rules (the noisy-detector lesson): FAIL only on comment/phrase-anchored
# markers; the word `placeholder` in attribute/property/identifier position is
# STANDARD UI vocabulary (TextField placeholder:, ::placeholder, fooPlaceholder)
# and must never fire. Scope: product source only (tests/spec/fixtures/mocks and
# *.md excluded). Consent tokens live in docs/project/decisions.md (or truth/position.md
# for projects with an upstream product lock) as
# [placeholder-consent: <path-or-part> <what> owner <date>]; a token downgrades ONLY
# hits its <path-or-part> covers (substring match on the hit's path): one token
# never whitelists the whole repo.
PEX="$EX --exclude-dir=fixtures --exclude-dir=mocks --exclude-dir=__mocks__ --exclude=*.md"
PL_HITS=$(grep -rInE $PEX \
  --include='*.swift' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' --include='*.py' --include='*.go' --include='*.rs' \
  -e 'lorem ipsum' -e 'TODO:? *replace' -e 'FIXME.*real (data|impl)' \
  -e '(//|#|/\*|<!--).*\bplaceholder\b' . 2>/dev/null \
  | grep -viE '(\.test\.|\.spec\.|/tests?/|/spec/)' \
  | grep -viE 'placeholder[=:(]|[a-z]Placeholder\b|::placeholder|\.placeholder\b' | head -20)
CONSENTS=""
for cf in truth/position.md docs/project/decisions.md intent-anchor.md; do
  if [ -f "$cf" ]; then
    CONSENTS="$CONSENTS $(grep -oE '\[placeholder-consent: [^ ]+' "$cf" 2>/dev/null | sed 's/\[placeholder-consent: //' | tr '\n' ' ')"
  fi
done
PL_FAIL=""
PL_WARN_COVERED=""
if [ -n "$PL_HITS" ]; then
  while IFS= read -r hit; do
    hitpath="${hit%%:*}"
    covered=""
    for scope in $CONSENTS; do
      case "$hitpath" in *"$scope"*) covered=1 ;; esac
    done
    if [ -n "$covered" ]; then
      PL_WARN_COVERED="$PL_WARN_COVERED$hit ; "
    else
      PL_FAIL="$PL_FAIL$hit ; "
    fi
  done <<EOF_PL
$PL_HITS
EOF_PL
fi
if [ -n "$PL_FAIL" ]; then
  report FAIL placeholder-lint "unconsented stand-in marker(s) on the product path (report before writing; a consent token is required): ${PL_FAIL:0:300}"
else
  report PASS placeholder-lint "no unconsented stand-in markers"
fi
if [ -n "$PL_WARN_COVERED" ]; then
  report WARN placeholder-consented "consent-covered marker(s), confirm scope still matches: ${PL_WARN_COVERED:0:200}"
fi
PL_SOFT=$(grep -rInE $PEX --include='*.swift' --include='*.ts' --include='*.tsx' \
  -e '\b(MockService|FakeData|DummyData|sampleData|sample_data)\b' . 2>/dev/null \
  | grep -viE '(\.test\.|\.spec\.|/tests?/|/spec/|Preview)' | head -5 | tr '\n' ' ')
if [ -n "${PL_SOFT// /}" ]; then
  report WARN placeholder-soft "stand-in-named symbols in product dirs (check consent/contract): $PL_SOFT"
fi

# ---- AI traces -----------------------------------------------------------------
AITR=$(grep -rIl $EX -e 'Co-Authored-By: Claude' -e 'Generated with \[Claude' -e 'Generated with Claude Code' -e '🤖 Generated' . 2>/dev/null | head -5 | tr '\n' ' ')
if [ -n "${AITR// /}" ]; then
  report FAIL ai-traces "AI fingerprints in: $AITR"
else
  report PASS ai-traces "no AI fingerprints"
fi
# Committed build-record files read as a human team's documents: no pipeline or tooling names in them.
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  TRACKED=$(git ls-files -- docs/project AGENTS.md CLAUDE.md 2>/dev/null | grep -E '\.md$')
  PT=""
  if [ -n "$TRACKED" ]; then
    PT=$(printf '%s\n' "$TRACKED" | tr '\n' '\0' | xargs -0 grep -lE \
      -e '(^|[^A-Za-z0-9])/(plan|dev|gate|loyal|scout|handoff|capture|fix|deploy|explain|polish|inbox|next) (M[0-9]+|adopt|amend|convert|freeze|resume|accept|check|status|vigilance|write|receive|ask|map|spike|offload|ingest|add|review|list|auto)([^A-Za-z]|$)' \
      -e 'code-verifier|loyal-evaluator|gate-judge|cold-reader|claim-verifier|heavy\.py|milestone_lint|render_pack|run_isolated|gate_run\.py|gate_report|record_check|helm_stamp' \
      -e 'rulings\.py|intent_lock|inbox\.py|project_status|continuity\.py|local_only\.py|gate_copies|handoff_check|milestone-continue|heavy-guard|reload-gate|typecheck-once' \
      2>/dev/null | head -5 | tr '\n' ' ')
  fi
  if [ -n "${PT// /}" ]; then
    report FAIL pipeline-traces "tooling names in committed build-record files (keep them in local-only files): $PT"
  else
    report PASS pipeline-traces "committed build-record files carry no tooling names"
  fi
else
  report SKIP pipeline-traces "not a git repo"
fi
if [ -f .gitignore ] && grep -qE '(^|/)\.claude' .gitignore; then
  report WARN gitignore ".gitignore lists .claude (reveals tooling; remove it)"
fi

# ---- complexity / clones ---------------------------------------------------------
CPLX=0
if command -v radon >/dev/null 2>&1; then
  if find . -name '*.py' -not -path './.venv/*' -not -path './node_modules/*' 2>/dev/null | head -1 | grep -q .; then
    R=$(radon cc -n D . 2>/dev/null | head -5 | tr '\n' ' ')
    if [ -n "${R// /}" ]; then
      report WARN complexity "functions at grade D or worse: $R"
    else
      report PASS complexity "radon: nothing at grade D or worse"
    fi
    CPLX=1
  fi
fi
if command -v jscpd >/dev/null 2>&1 && [ -f package.json ]; then
  if jscpd --silent --threshold 10 . >/dev/null 2>&1; then
    report PASS clones "jscpd: duplication under 10%"
  else
    report WARN clones "jscpd: duplication above 10%"
  fi
  CPLX=1
fi
if [ $CPLX -eq 0 ]; then
  report SKIP complexity "no complexity/clone tool installed (radon, jscpd)"
fi

# ---- summary ---------------------------------------------------------------------
echo
if [ $FAILS -gt 0 ]; then
  echo "RESULT: FAIL  ($FAILS failing check(s), $WARNS warning(s))"
  exit 1
fi
echo "RESULT: PASS  ($WARNS warning(s))"
exit 0
