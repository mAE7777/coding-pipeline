#!/bin/bash
# Stop hook: flag console.log / console.debug / debugger left in JS and TS files changed in this working tree
# (tests, configs, type declarations, JSON, and Markdown are skipped). Whether a milestone is finished is
# checked elsewhere (the build's own stop check and the gate); this hook only catches debug leftovers.
# Output is always JSON so a plain-text reply can never be mistaken for a user turn.

INPUT=$(cat)
CWD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("cwd",""))' 2>/dev/null)
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
  printf '{"suppressOutput": true}\n'
  exit 0
fi

WARNINGS=""
MODIFIED=$(git -C "$CWD" diff --name-only HEAD 2>/dev/null; git -C "$CWD" ls-files --others --exclude-standard 2>/dev/null)
for f in $(printf '%s\n' "$MODIFIED" | sort -u); do
  case "$f" in
    *.test.*|*.spec.*|*__tests__/*|*.config.*|*.d.ts|*.json|*.md) continue ;;
  esac
  case "$f" in
    *.ts|*.tsx|*.js|*.jsx)
      if [ -f "$CWD/$f" ]; then
        HITS=$(grep -n 'console\.\(log\|debug\)\|debugger' "$CWD/$f" 2>/dev/null | head -5)
        if [ -n "$HITS" ]; then
          WARNINGS="${WARNINGS}NOTE: console.log/debugger found in ${f}:\n${HITS}\n\n"
        fi
      fi
      ;;
  esac
done

if [ -n "$WARNINGS" ]; then
  ESCAPED=$(printf '%b' "$WARNINGS" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
  printf '{"systemMessage": %s}\n' "$ESCAPED"
else
  printf '{"suppressOutput": true}\n'
fi
exit 0
