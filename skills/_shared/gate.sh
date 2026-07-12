#!/bin/bash
# gate.sh - deterministic rot/security gate for the coding pipeline.
# Sole owner in the loop: /qa. /loyal runs it only standalone; /deploy re-runs it at release.
# Every check prints PASS / FAIL / WARN / SKIP; a SKIP is named, never implied as a pass.
# Exit 0 = no FAIL. Exit 1 = at least one FAIL. Exit 2 = bad invocation.
# Usage: gate.sh [project-dir]

set -u

DIR="${1:-.}"
cd "$DIR" 2>/dev/null || { echo "gate: cannot cd to $DIR" >&2; exit 2; }

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
    --exclude=*.min.js --exclude=*.map --exclude=*.lock --exclude=package-lock.json
    --exclude=gate.sh"

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
if [ $LINTED -eq 0 ]; then
  report SKIP lint "no recognized linter (npm lint script / ruff / clippy / go vet)"
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
if [ $BUILT -eq 0 ]; then
  report SKIP typecheck "no tsconfig.json / Cargo.toml / go.mod"
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

# ---- AI traces -----------------------------------------------------------------
AITR=$(grep -rIl $EX -e 'Co-Authored-By: Claude' -e 'Generated with \[Claude' -e 'Generated with Claude Code' -e '🤖 Generated' . 2>/dev/null | head -5 | tr '\n' ' ')
if [ -n "${AITR// /}" ]; then
  report FAIL ai-traces "AI fingerprints in: $AITR"
else
  report PASS ai-traces "no AI fingerprints"
fi
if [ -f .gitignore ] && grep -qE '(^|/)\.claude' .gitignore; then
  report WARN gitignore ".gitignore lists .claude (reveals tooling; remove per working rules)"
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
